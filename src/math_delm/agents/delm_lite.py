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
from src.math_delm.repair.clustering import build_worker_clusters
from src.math_delm.repair.diagnostic import run_diagnostic_critic
from src.math_delm.repair.equivalence import answer_in_list, safe_verify_feedback, verify_answer_with_details
from src.math_delm.repair.selector import run_delm_selector
from src.math_delm.repair.shared_context import admit_round_worker_notes, get_rejected_answers_from_shared_context, update_shared_context_after_round
from src.math_delm.agents.main_agent import case_raw_correct, raw_selected_answer


@dataclass
class DelmLiteConfig:
    max_rounds: int = 5
    workers: int = 2
    max_tokens: int = 4096
    temperature: float = 0.7
    selector_mode: str = "deterministic"


@dataclass
class DelmLiteResult:
    record: dict[str, Any]


def raw_vote_already_correct_delm_result(case: dict[str, Any]) -> dict[str, Any]:
    answer = raw_selected_answer(case)

    return {
        "method": "DELM-lite Feedback Retry",
        "solved": True,
        "final_answer": answer,
        "correct": True,
        "rounds_used": 0,
        "stop_reason": "raw_vote_already_correct",
        "rounds": [],
        "final_shared_context": {
            "rejected_answers": [],
            "failed_attempt_summaries": [],
            "round_notes": [],
            "diagnostics": [],
            "banned_assumptions": [],
            "must_check_items": [],
            "strategy_hints": [],
            "verified_notes": [],
            "rejected_notes": [],
            "note_admission_log": [],
        },
        "raw_selected_answer": answer,
        "raw_correct": True,
        "wrong_submitted_answers": [],
        "repeated_wrong_answer_count": 0,
        "duplicate_forbidden_answer_count": 0,
        "invalid_answer_count": 0,
        "truncated_answer_count": 0,
        "parser_invalid_count": 0,
        "latent_worker_solved": False,
        "api_calls": 0,
        "diagnostic_calls": 0,
        "diagnostic_tokens": 0,
        "verifier_calls": 0,
        "verifier_tokens": 0,
        "verified_notes_added": 0,
        "rejected_notes_count": 0,
        "uncertain_notes_count": 0,
        "admission_evaluations": 0,
        "admission_calls": 0,
        "admission_tokens": 0,
        "strict_equiv_false_positives_prevented": 0,
        "verified_support_selected_count": 0,
        "verified_blocked_candidate_count": 0,
        "usage": {},
        "wall_time_seconds": 0.0,
    }


def get_worker_role(worker_id: int) -> str:
    if not cfg.USE_TASK_QUEUE:
        return "general_solver"
    if cfg.TASK_QUEUE_MODE != "static":
        return "general_solver"
    return cfg.TASK_QUEUE_ROLES[worker_id % len(cfg.TASK_QUEUE_ROLES)]


def run_delm_workers(
    client,
    case: dict[str, Any],
    round_id: int,
    shared_context: dict[str, Any],
) -> list[dict[str, Any]] | None:
    from src.math_delm.prompts.delm_worker import build_delm_worker_prompt

    outputs = []
    rejected_answers = get_rejected_answers_from_shared_context(shared_context)

    for worker_id in range(cfg.DELM_WORKERS):
        worker_role = get_worker_role(worker_id)
        print(f"--- DELM worker {worker_id}, round {round_id}/{cfg.MAX_ROUNDS} ---")

        prompt = build_delm_worker_prompt(
            case=case,
            round_id=round_id,
            worker_id=worker_id,
            shared_context=shared_context,
        )

        result = call_llm(client, prompt, temperature=cfg.TEMPERATURE)

        if result.get("error") is not None or result.get("finish_reason") == "api_error":
            append_jsonl(cfg.ERROR_PATH, {
                "id": case.get("id"),
                "method": "delm_lite",
                "round": round_id,
                "worker_id": worker_id,
                "stage": "worker",
                "result": result,
            })
            print("[SKIP] DELM worker API error.")
            return None

        parsed = extract_json_object(result.get("content"))
        answer = parse_answer_from_output(result.get("content"), parsed)
        invalid_answer = not is_valid_answer(answer)
        duplicate_rejected_answer = False if invalid_answer else answer_in_list(answer, rejected_answers)

        if invalid_answer or duplicate_rejected_answer:
            correct = False
            verification = {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": cfg.USE_STRICT_EQUIV,
            }
        else:
            correct, verification = verify_answer_with_details(case.get("gold"), answer)

        output = {
            "worker_id": worker_id,
            "role": worker_role,
            "round": round_id,
            "answer": answer,
            "correct": correct,
            "strict_equivalence": verification,
            "invalid_answer": invalid_answer,
            "duplicate_rejected_answer": duplicate_rejected_answer,
            "intermediate_claims": (parsed or {}).get("intermediate_claims", []) if isinstance(parsed, dict) else [],
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
            "wall_time_seconds": result.get("wall_time_seconds"),
        }

        outputs.append(output)

        print("worker answer:", short_text(answer, 120))
        print("worker latent correct:", correct)
        print("worker invalid answer:", invalid_answer)
        print("worker duplicate rejected:", duplicate_rejected_answer)

        time.sleep(cfg.SLEEP_SECONDS)

    return outputs


def make_note_admission_settings(client) -> dict[str, Any]:
    return {
        "client": client,
        "admission_max_tokens": cfg.ADMISSION_MAX_TOKENS,
        "admission_temperature": cfg.ADMISSION_TEMPERATURE,
        "use_llm_admission_fallback": cfg.USE_LLM_ADMISSION,
    }


def run_delm_lite_feedback_retry(client, case: dict[str, Any]) -> dict[str, Any] | None:
    if cfg.USE_RAW_INIT and case_raw_correct(case) is True:
        return raw_vote_already_correct_delm_result(case)

    started = time.perf_counter()

    rounds = []
    shared_context: dict[str, Any] = {
        "rejected_answers": [],
        "failed_attempt_summaries": [],
        "round_notes": [],
        "diagnostics": [],
        "banned_assumptions": [],
        "must_check_items": [],
        "strategy_hints": [],
        "verified_notes": [],
        "rejected_notes": [],
        "note_admission_log": [],
    }

    solved = False
    final_answer = None
    stop_reason = "max_rounds_reached"
    latent_worker_solved = False

    if cfg.USE_RAW_INIT and case_raw_correct(case) is False:
        answer = raw_selected_answer(case)
        if is_valid_answer(answer):
            shared_context["rejected_answers"].append({
                "round": 0,
                "answer": answer,
                "oracle_feedback": "incorrect_raw_vote",
            })
        shared_context["round_notes"].append({
            "round": 0,
            "submitted_answer": answer,
            "feedback": "incorrect_raw_vote",
            "worker_candidate_summaries": [],
        })

    for round_id in range(1, cfg.MAX_ROUNDS + 1):
        print(f"--- DELM-lite round {round_id}/{cfg.MAX_ROUNDS} ---")

        context_before = json.loads(json.dumps(shared_context, ensure_ascii=False))

        worker_outputs = run_delm_workers(client, case, round_id, shared_context)
        if worker_outputs is None:
            return None

        if cfg.TRACK_LATENT_WORKER_SOLVE and any(w.get("correct") is True for w in worker_outputs):
            latent_worker_solved = True

        note_admission = {
            "verified_notes": [],
            "rejected_notes": [],
            "admission_results": [],
            "admission_evaluations": 0,
            "admission_calls": 0,
            "admission_tokens": 0,
        }
        if cfg.USE_VERIFIED_NOTES:
            note_admission = admit_round_worker_notes(
                client=client,
                case=case,
                worker_outputs=worker_outputs,
                shared_context=shared_context,
            )

        context_after_admission = json.loads(json.dumps(shared_context, ensure_ascii=False))

        rejected_answers = get_rejected_answers_from_shared_context(shared_context)
        clusters = build_worker_clusters(worker_outputs, rejected_answers)

        selector = run_delm_selector(
            client=client,
            case=case,
            round_id=round_id,
            shared_context=shared_context,
            worker_outputs=worker_outputs,
            clusters=clusters,
        )
        if selector is None:
            return None

        submitted_answer = normalize_answer(selector.get("selected_answer"))
        correct = selector.get("correct") is True

        if cfg.USE_DIAGNOSTIC and correct is not True and is_valid_answer(submitted_answer):
            rejected_answers_for_diagnostic = get_rejected_answers_from_shared_context(shared_context)
            rejected_answers_for_diagnostic.append(submitted_answer)
            selector["diagnostic"] = run_diagnostic_critic(
                client=client,
                case=case,
                wrong_answer=submitted_answer,
                wrong_record=selector,
                rejected_answers=rejected_answers_for_diagnostic,
                method_name="DELM-lite Feedback Retry",
            )

        round_record = {
            "round": round_id,
            "context_before": context_before,
            "context_after_admission": context_after_admission,
            "workers": worker_outputs,
            "note_admission": note_admission,
            "clusters": clusters,
            "selector": selector,
            "submitted_answer": submitted_answer,
            "correct": correct,
        }

        rounds.append(round_record)

        final_answer = submitted_answer

        if correct:
            solved = True
            stop_reason = "solved"
            break

        shared_context = update_shared_context_after_round(shared_context, round_record)

        time.sleep(cfg.SLEEP_SECONDS)

    ended = time.perf_counter()

    usage_items = []
    for round_record in rounds:
        usage_items.extend(round_record.get("workers", []))
        selector = round_record.get("selector")
        if isinstance(selector, dict) and selector.get("api_call") is not False:
            usage_items.append(selector)

    wrong_answers = [
        normalize_answer(r.get("submitted_answer"))
        for r in rounds
        if r.get("correct") is not True and normalize_answer(r.get("submitted_answer")) is not None
    ]
    duplicate_forbidden_answer_count = sum(
        1 for round_record in rounds
        if (round_record.get("selector") or {}).get("selector_selected_rejected_answer") is True
    )
    invalid_answer_count = 0
    truncated_answer_count = 0
    parser_invalid_count = 0

    for round_record in rounds:
        worker_invalid_metrics = invalid_metric_counts(
            round_record.get("workers", []),
            "invalid_answer",
        )
        invalid_answer_count += worker_invalid_metrics["invalid_answer_count"]
        truncated_answer_count += worker_invalid_metrics["truncated_answer_count"]
        parser_invalid_count += worker_invalid_metrics["parser_invalid_count"]

        selector = round_record.get("selector") or {}
        selector_invalid_metrics = invalid_metric_counts([selector], "invalid_selected_answer")
        invalid_answer_count += selector_invalid_metrics["invalid_answer_count"]
        truncated_answer_count += selector_invalid_metrics["truncated_answer_count"]
        parser_invalid_count += selector_invalid_metrics["parser_invalid_count"]

    diagnostics = [
        (round_record.get("selector") or {}).get("diagnostic")
        for round_record in rounds
        if isinstance((round_record.get("selector") or {}).get("diagnostic"), dict)
    ]
    diagnostic_calls = sum(
        1 for diagnostic in diagnostics
        if diagnostic.get("api_call") is True
    )
    diagnostic_tokens = sum(
        usage_total_tokens(diagnostic.get("usage"))
        for diagnostic in diagnostics
    )
    verifier_evaluations = [
        evaluation
        for round_record in rounds
        for evaluation in ((round_record.get("selector") or {}).get("verifier_evaluations") or [])
        if isinstance(evaluation, dict)
    ]
    verifier_calls = sum(
        1 for evaluation in verifier_evaluations
        if evaluation.get("api_call") is True
    )
    verifier_tokens = sum(
        usage_total_tokens(evaluation.get("usage"))
        for evaluation in verifier_evaluations
    )
    admission_evaluations = sum(
        cfg.to_int((round_record.get("note_admission") or {}).get("admission_evaluations"), 0) or 0
        for round_record in rounds
    )
    admission_calls = sum(
        cfg.to_int((round_record.get("note_admission") or {}).get("admission_calls"), 0) or 0
        for round_record in rounds
    )
    admission_tokens = sum(
        cfg.to_int((round_record.get("note_admission") or {}).get("admission_tokens"), 0) or 0
        for round_record in rounds
    )
    verified_notes_added = sum(
        len((round_record.get("note_admission") or {}).get("verified_notes", []) or [])
        for round_record in rounds
    )
    rejected_notes_count = 0
    uncertain_notes_count = 0
    strict_equiv_false_positives_prevented = 0
    verified_support_selected_count = 0
    verified_blocked_candidate_count = 0

    for round_record in rounds:
        note_admission = round_record.get("note_admission") or {}
        for result in note_admission.get("admission_results", []) or []:
            status = result.get("status")
            if status == "rejected":
                rejected_notes_count += 1
            elif status == "uncertain":
                uncertain_notes_count += 1

        selector = round_record.get("selector") or {}
        strict_details = selector.get("strict_equivalence") or {}
        if (
            strict_details.get("original_equiv_result") is True
            and strict_details.get("strict_equiv_result") is False
            and strict_details.get("final_equiv_result") is False
        ):
            strict_equiv_false_positives_prevented += 1

        if cfg.to_int(selector.get("verified_support_count"), 0):
            verified_support_selected_count += 1

        for cluster_score in selector.get("cluster_scores", []) or []:
            if cfg.to_int(cluster_score.get("verified_block_count"), 0):
                verified_blocked_candidate_count += 1

        for worker in round_record.get("workers", []) or []:
            strict_details = worker.get("strict_equivalence") or {}
            if (
                strict_details.get("original_equiv_result") is True
                and strict_details.get("strict_equiv_result") is False
                and strict_details.get("final_equiv_result") is False
            ):
                strict_equiv_false_positives_prevented += 1

    usage = sum_usage(usage_items)

    return {
        "method": "DELM-lite Feedback Retry",
        "solved": solved,
        "final_answer": final_answer,
        "correct": solved,
        "rounds_used": len(rounds),
        "stop_reason": stop_reason,
        "rounds": rounds,
        "final_shared_context": shared_context,
        "wrong_submitted_answers": wrong_answers,
        "repeated_wrong_answer_count": repeated_wrong_answer_count(wrong_answers),
        "duplicate_forbidden_answer_count": duplicate_forbidden_answer_count,
        "invalid_answer_count": invalid_answer_count,
        "truncated_answer_count": truncated_answer_count,
        "parser_invalid_count": parser_invalid_count,
        "latent_worker_solved": latent_worker_solved,
        "api_calls": len(usage_items),
        "diagnostic_calls": diagnostic_calls,
        "diagnostic_tokens": diagnostic_tokens,
        "verifier_calls": verifier_calls,
        "verifier_tokens": verifier_tokens,
        "verified_notes_added": verified_notes_added,
        "rejected_notes_count": rejected_notes_count,
        "uncertain_notes_count": uncertain_notes_count,
        "admission_evaluations": admission_evaluations,
        "admission_calls": admission_calls,
        "admission_tokens": admission_tokens,
        "strict_equiv_false_positives_prevented": strict_equiv_false_positives_prevented,
        "verified_support_selected_count": verified_support_selected_count,
        "verified_blocked_candidate_count": verified_blocked_candidate_count,
        "usage": usage,
        "wall_time_seconds": ended - started,
    }
