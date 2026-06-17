from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from typing import Any

from src.math_delm.utils import (
    append_jsonl,
    call_chat_completion,
    cluster_answers,
    equivalent,
    extract_boxed,
    get_client,
    load_done_ids,
    md_table,
    normalize_answer,
    pct,
    read_jsonl,
    safe_verify,
    short_text,
    tail_text,
    write_jsonl,
)
from src.math_delm import config as cfg
from src.math_delm.repair.math_note_tools import parse_integer_set, parse_integer_value, strict_equivalence_check
from src.math_delm.repair.verified_notes import admit_worker_claims, format_verified_notes

from dataclasses import dataclass

from src.math_delm.llm.client import call_llm
from src.math_delm.evaluation.metrics import (
    invalid_metric_counts,
    repeated_wrong_answer_count,
    sum_usage,
    usage_total_tokens,
)
from src.math_delm.repair.answer_parser import extract_json_object, is_parser_invalid_item, is_truncated_answer_item, is_valid_answer, parse_answer_from_output
from src.math_delm.repair.diagnostic import run_diagnostic_critic, wrong_record_reason
from src.math_delm.repair.equivalence import answer_in_list, safe_verify_feedback, verify_answer_with_details


@dataclass
class MainAgentConfig:
    max_rounds: int = 5
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class MainAgentResult:
    record: dict[str, Any]


def normalized_wrong_answers(attempts: list[dict[str, Any]], answer_key: str = "answer") -> list[str]:
    wrong = []

    for attempt in attempts:
        if attempt.get("correct") is True:
            continue

        answer = normalize_answer(attempt.get(answer_key))
        if answer is not None:
            wrong.append(answer)

    return wrong


def make_forbidden_answers_text(attempts: list[dict[str, Any]]) -> str:
    forbidden_answers = normalized_wrong_answers(attempts, "answer")

    if not forbidden_answers:
        return "No forbidden answers yet."

    lines = []
    for i, answer in enumerate(forbidden_answers, start=1):
        lines.append(f"{i}. {answer}")

    return "\n".join(lines)


def make_previous_attempts_text(attempts: list[dict[str, Any]]) -> str:
    if not attempts:
        return "No previous attempts."

    lines = []

    for attempt in attempts:
        answer = normalize_answer(attempt.get("answer"))
        parsed = attempt.get("parsed") or {}

        lines.append(f"Round {attempt.get('round')}:")
        lines.append(f"- previous answer: {answer}")
        lines.append(f"- oracle feedback: {attempt.get('oracle_feedback') or 'incorrect'}")

        strategy = parsed.get("strategy") or parsed.get("reason") or parsed.get("used_context")
        if strategy:
            lines.append(f"- previous strategy/reason: {short_text(strategy, 300)}")

        lines.append("")

    return "\n".join(lines).strip()


def make_diagnostic_history_text(attempts: list[dict[str, Any]]) -> str:
    diagnostic_attempts = [
        attempt for attempt in attempts
        if isinstance(attempt.get("diagnostic"), dict)
    ]

    if not diagnostic_attempts:
        return "No diagnostic feedback yet."

    lines = []
    for attempt in diagnostic_attempts:
        diagnostic = attempt.get("diagnostic") or {}
        must_check = diagnostic.get("must_check") or []
        lines.append(f"- rejected answer: {normalize_answer(attempt.get('answer'))}")
        lines.append(f"  likely error type: {diagnostic.get('likely_error_type')}")
        lines.append(f"  banned assumption: {diagnostic.get('banned_assumption') or ''}")
        lines.append(f"  must check: {', '.join(str(item) for item in must_check) if must_check else ''}")
        lines.append(f"  next strategy hint: {diagnostic.get('next_strategy_hint') or ''}")

    return "\n".join(lines)


def case_raw_correct(case: dict[str, Any]) -> bool | None:
    value = case.get("raw_correct")

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False

    return None


def raw_selected_answer(case: dict[str, Any]) -> str | None:
    return normalize_answer(case.get("raw_selected_answer"))


def make_raw_vote_seed_attempt(case: dict[str, Any]) -> dict[str, Any]:
    answer = raw_selected_answer(case)

    return {
        "round": 0,
        "answer": answer,
        "correct": False,
        "invalid_answer": not is_valid_answer(answer),
        "duplicate_forbidden_answer": False,
        "oracle_feedback": "incorrect_raw_vote",
        "parsed": {"source": "raw_vote"},
        "raw_output": "",
        "parser_debug": {
            "parsed_json": False,
            "parsed_keys": [],
            "extracted_answer": answer,
            "raw_output_tail": "",
        },
        "finish_reason": "raw_vote_init",
        "usage": {},
        "api_call": False,
        "wall_time_seconds": 0.0,
    }


def raw_vote_already_correct_main_result(case: dict[str, Any]) -> dict[str, Any]:
    answer = raw_selected_answer(case)

    return {
        "method": "Main-Agent Feedback Retry",
        "solved": True,
        "final_answer": answer,
        "correct": True,
        "rounds_used": 0,
        "stop_reason": "raw_vote_already_correct",
        "attempts": [],
        "raw_selected_answer": answer,
        "raw_correct": True,
        "wrong_submitted_answers": [],
        "repeated_wrong_answer_count": 0,
        "duplicate_forbidden_answer_count": 0,
        "invalid_answer_count": 0,
        "truncated_answer_count": 0,
        "parser_invalid_count": 0,
        "api_calls": 0,
        "diagnostic_calls": 0,
        "diagnostic_tokens": 0,
        "verifier_calls": 0,
        "verifier_tokens": 0,
        "usage": {},
        "wall_time_seconds": 0.0,
    }


def run_main_agent_feedback_retry(client, case: dict[str, Any]) -> dict[str, Any] | None:
    from src.math_delm.prompts.main_agent import build_main_agent_prompt

    if cfg.USE_RAW_INIT and case_raw_correct(case) is True:
        return raw_vote_already_correct_main_result(case)

    started = time.perf_counter()
    attempts = []
    solved = False
    final_answer = None
    stop_reason = "max_rounds_reached"

    if cfg.USE_RAW_INIT and case_raw_correct(case) is False:
        attempts.append(make_raw_vote_seed_attempt(case))

    for round_id in range(1, cfg.MAX_ROUNDS + 1):
        print(f"--- Main-Agent round {round_id}/{cfg.MAX_ROUNDS} ---")

        prompt = build_main_agent_prompt(case, round_id, attempts)
        result = call_llm(client, prompt, temperature=cfg.TEMPERATURE)

        if result.get("error") is not None or result.get("finish_reason") == "api_error":
            append_jsonl(cfg.ERROR_PATH, {
                "id": case.get("id"),
                "method": "main_agent",
                "round": round_id,
                "stage": "solve",
                "result": result,
            })
            print("[SKIP] Main-Agent API error.")
            return None

        parsed = extract_json_object(result.get("content"))
        answer = parse_answer_from_output(result.get("content"), parsed)
        previous_wrong_answers = normalized_wrong_answers(attempts, "answer")
        invalid_answer = not is_valid_answer(answer)
        duplicate_forbidden = False if invalid_answer else answer_in_list(answer, previous_wrong_answers)

        if invalid_answer:
            correct = False
            oracle_feedback = "invalid_or_unparseable_answer"
            verification = {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": cfg.USE_STRICT_EQUIV,
            }
        elif duplicate_forbidden:
            correct = False
            oracle_feedback = "incorrect_repeated_forbidden_answer"
            verification = {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": cfg.USE_STRICT_EQUIV,
            }
        else:
            correct, verification = verify_answer_with_details(case.get("gold"), answer)
            oracle_feedback = "correct" if correct else "incorrect"

        attempt = {
            "round": round_id,
            "answer": answer,
            "correct": correct,
            "invalid_answer": invalid_answer,
            "duplicate_forbidden_answer": duplicate_forbidden,
            "oracle_feedback": oracle_feedback,
            "strict_equivalence": verification,
            "parsed": parsed,
            "raw_output": result.get("content", ""),
            "parser_debug": {
                "parsed_json": parsed is not None,
                "parsed_keys": list(parsed.keys()) if parsed else [],
                "extracted_answer": answer,
                "raw_output_tail": tail_text(result.get("content", ""), 500),
            },
            "finish_reason": result.get("finish_reason"),
            "usage": result.get("usage"),
            "api_call": True,
            "wall_time_seconds": result.get("wall_time_seconds"),
        }

        if cfg.USE_DIAGNOSTIC and oracle_feedback == "incorrect":
            attempt["diagnostic"] = run_diagnostic_critic(
                client=client,
                case=case,
                wrong_answer=answer,
                wrong_record=attempt,
                rejected_answers=normalized_wrong_answers(attempts + [attempt], "answer"),
                method_name="Main-Agent Feedback Retry",
            )

        attempts.append(attempt)

        print("main answer:", short_text(answer, 120))
        print("main correct:", correct)
        print("main invalid answer:", invalid_answer)
        print("main duplicate forbidden:", duplicate_forbidden)

        final_answer = answer

        if correct:
            solved = True
            stop_reason = "solved"
            break

        time.sleep(cfg.SLEEP_SECONDS)

    ended = time.perf_counter()

    wrong_answers = normalized_wrong_answers(attempts, "answer")
    api_attempts = [
        attempt for attempt in attempts
        if attempt.get("api_call") is not False
    ]
    duplicate_forbidden_answer_count = sum(
        1 for attempt in attempts
        if attempt.get("api_call") is not False
        and attempt.get("duplicate_forbidden_answer") is True
    )
    invalid_metrics = invalid_metric_counts(api_attempts, "invalid_answer")
    usage = sum_usage(api_attempts)
    diagnostics = [
        attempt.get("diagnostic")
        for attempt in attempts
        if isinstance(attempt.get("diagnostic"), dict)
    ]
    diagnostic_calls = sum(
        1 for diagnostic in diagnostics
        if diagnostic.get("api_call") is True
    )
    diagnostic_tokens = sum(
        usage_total_tokens(diagnostic.get("usage"))
        for diagnostic in diagnostics
    )

    return {
        "method": "Main-Agent Feedback Retry",
        "solved": solved,
        "final_answer": final_answer,
        "correct": solved,
        "rounds_used": len(api_attempts),
        "stop_reason": stop_reason,
        "attempts": attempts,
        "wrong_submitted_answers": wrong_answers,
        "repeated_wrong_answer_count": repeated_wrong_answer_count(wrong_answers),
        "duplicate_forbidden_answer_count": duplicate_forbidden_answer_count,
        **invalid_metrics,
        "api_calls": len(api_attempts),
        "diagnostic_calls": diagnostic_calls,
        "diagnostic_tokens": diagnostic_tokens,
        "usage": usage,
        "wall_time_seconds": ended - started,
    }
