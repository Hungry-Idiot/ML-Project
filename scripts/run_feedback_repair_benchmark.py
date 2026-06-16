import os
import re
import sys
import json
import time
from pathlib import Path
from typing import Any
from collections import Counter, defaultdict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    read_jsonl,
    write_jsonl,
    append_jsonl,
    load_done_ids,
    get_client,
    call_chat_completion,
    safe_verify,
    equivalent,
    normalize_answer,
    extract_boxed,
    cluster_answers,
    pct,
    short_text,
    tail_text,
    md_table,
)
from scripts.math_note_tools import parse_integer_set, parse_integer_value, strict_equivalence_check
from scripts.verified_notes import admit_worker_claims, format_verified_notes


INPUT_PATH = Path("outputs/amo_parser_sc3_analysis_cases.jsonl")

OUT_PATH = Path("outputs/feedback_repair_benchmark.jsonl")
ERROR_PATH = Path("outputs/feedback_repair_benchmark_api_errors.jsonl")
OUT_MD = Path("outputs/feedback_repair_benchmark_report.md")
OUT_SUMMARY_JSON = Path("outputs/feedback_repair_benchmark_summary.json")

MAX_TOKENS = int(os.getenv("FEEDBACK_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("FEEDBACK_TEMPERATURE", "0.7"))
SELECTOR_TEMPERATURE = float(os.getenv("FEEDBACK_SELECTOR_TEMPERATURE", "0.2"))
SLEEP_SECONDS = float(os.getenv("FEEDBACK_SLEEP", "0.5"))
USE_DIAGNOSTIC = os.getenv("FEEDBACK_USE_DIAGNOSTIC", "0") == "1"
DIAG_MAX_TOKENS = int(os.getenv("FEEDBACK_DIAG_MAX_TOKENS", "512"))
DIAG_TEMPERATURE = float(os.getenv("FEEDBACK_DIAG_TEMPERATURE", "0.2"))
USE_VERIFIED_NOTES = os.getenv("FEEDBACK_USE_VERIFIED_NOTES", "0") == "1"
USE_STRICT_EQUIV = os.getenv("FEEDBACK_USE_STRICT_EQUIV", "1") == "1"
USE_TASK_QUEUE = os.getenv("FEEDBACK_USE_TASK_QUEUE", "0") == "1"
TASK_QUEUE_MODE = os.getenv("FEEDBACK_TASK_QUEUE_MODE", "static")
ADMISSION_MAX_TOKENS = int(os.getenv("FEEDBACK_ADMISSION_MAX_TOKENS", "512"))
ADMISSION_TEMPERATURE = float(os.getenv("FEEDBACK_ADMISSION_TEMPERATURE", "0.0"))
USE_LLM_ADMISSION = os.getenv("FEEDBACK_USE_LLM_ADMISSION", "1") == "1"

LIMIT = int(os.getenv("FEEDBACK_LIMIT", "0"))
ONLY_LOW_CONF = os.getenv("FEEDBACK_ONLY_LOW_CONF", "1") == "1"
LOW_CONF_MAX_SUPPORT = int(os.getenv("FEEDBACK_LOW_CONF_MAX_SUPPORT", "1"))
ONLY_RAW_WRONG = os.getenv("FEEDBACK_ONLY_RAW_WRONG", "0") == "1"
USE_RAW_INIT = os.getenv("FEEDBACK_USE_RAW_INIT", "0") == "1"

MAX_ROUNDS = int(os.getenv("FEEDBACK_MAX_ROUNDS", "5"))
DELM_WORKERS = int(os.getenv("FEEDBACK_DELM_WORKERS", "2"))

RUN_MAIN_AGENT = os.getenv("FEEDBACK_RUN_MAIN_AGENT", "1") == "1"
RUN_DELM_LITE = os.getenv("FEEDBACK_RUN_DELM_LITE", "1") == "1"
USE_LLM_SELECTOR = os.getenv("FEEDBACK_USE_LLM_SELECTOR", "1") == "1"
VERIFIER_MAX_TOKENS = int(os.getenv("FEEDBACK_VERIFIER_MAX_TOKENS", "512"))
VERIFIER_TEMPERATURE = float(os.getenv("FEEDBACK_VERIFIER_TEMPERATURE", "0.2"))

VALID_SELECTOR_MODES = {"deterministic", "verifier", "hybrid", "llm"}
SELECTOR_MODE_RAW = os.getenv("FEEDBACK_SELECTOR_MODE")
if SELECTOR_MODE_RAW is None or not SELECTOR_MODE_RAW.strip():
    SELECTOR_MODE = "llm" if USE_LLM_SELECTOR else "deterministic"
else:
    SELECTOR_MODE = SELECTOR_MODE_RAW.strip().lower()

if SELECTOR_MODE not in VALID_SELECTOR_MODES:
    raise ValueError(
        "Invalid FEEDBACK_SELECTOR_MODE="
        f"{SELECTOR_MODE!r}. Expected one of {sorted(VALID_SELECTOR_MODES)}."
    )

# 如果设为 1，则 DELM 在某一轮 worker 中只要有正确答案就算“latent solved”。
# 但主指标仍然以 selector 提交的 submitted_answer 是否正确为准。
TRACK_LATENT_WORKER_SOLVE = os.getenv("FEEDBACK_TRACK_LATENT_WORKER_SOLVE", "1") == "1"

STRATEGY_POOL = [
    "Try a direct algebraic derivation. Avoid repeating previous wrong answers.",
    "Try a combinatorial or counting-based approach. Check for off-by-one mistakes.",
    "Try a construction / extremal argument. Check boundary cases carefully.",
    "Try a modular, parity, or invariant-based approach if relevant.",
    "Try to verify constraints first, then derive the final answer.",
    "Try an independent solution path from scratch, not a minor variation of previous attempts.",
]


def to_int(x: Any, default: int | None = None) -> int | None:
    try:
        return int(x)
    except Exception:
        return default


def to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def answer_equiv(a: str | None, b: str | None) -> bool:
    a = normalize_answer(a)
    b = normalize_answer(b)

    if a is None and b is None:
        return True

    if a is None or b is None:
        return False

    if a == b:
        return True

    return equivalent(a, b)


def verify_answer_with_details(gold: str | None, answer: str | None) -> tuple[bool, dict[str, Any]]:
    original_result = safe_verify(gold, answer)
    strict_result = strict_equivalence_check(gold, answer) if USE_STRICT_EQUIV else None

    if USE_STRICT_EQUIV and strict_result is not None:
        final_result = strict_result
    else:
        final_result = original_result

    return bool(final_result), {
        "strict_equiv_result": strict_result,
        "original_equiv_result": original_result,
        "final_equiv_result": bool(final_result),
        "use_strict_equiv": USE_STRICT_EQUIV,
    }


def safe_verify_feedback(gold: str | None, answer: str | None) -> bool:
    correct, _ = verify_answer_with_details(gold, answer)
    return correct


def strip_think_blocks(text: str | None) -> str:
    if text is None:
        return ""

    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("```", "")
    return cleaned.strip()


def _json_object_or_none(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    if isinstance(parsed, dict):
        return parsed

    return None


def _extract_last_balanced_json_object(text: str) -> dict[str, Any] | None:
    starts = [match.start() for match in re.finditer(r"\{", text)]

    for start in reversed(starts):
        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    parsed = _json_object_or_none(text[start:index + 1])
                    if parsed is not None:
                        return parsed
                    break

    return None


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """
    utils 里没有 JSON 抽取函数，所以这里单独定义。
    用于从模型输出中尽量解析 JSON。
    """
    original = text or ""
    cleaned = strip_think_blocks(original)

    parsed = _json_object_or_none(cleaned.strip())
    if parsed is not None:
        return parsed

    parsed = _extract_last_balanced_json_object(cleaned)
    if parsed is not None:
        return parsed

    return _extract_last_balanced_json_object(original)


def _normalized_non_empty_answer(value: Any) -> str | None:
    answer = normalize_answer(value)

    if answer is None:
        return None

    invalid_values = {
        "",
        "none",
        "null",
        "n/a",
        "na",
        "no answer",
        "no_answer",
        "cannot determine",
        "unknown",
    }

    if answer.lower().strip() in invalid_values:
        return None

    return answer


def _answer_from_parsed(parsed: dict[str, Any] | None) -> str | None:
    if not parsed:
        return None

    for key in [
        "final_answer",
        "candidate_answer",
        "selected_answer",
        "submitted_answer",
        "answer",
    ]:
        value = _normalized_non_empty_answer(parsed.get(key))
        if value is not None:
            return value

    return None


def parse_answer_from_output(text: str | None, parsed: dict[str, Any] | None = None) -> str | None:
    value = _answer_from_parsed(parsed)
    if value is not None:
        return value

    if parsed is None:
        parsed = extract_json_object(text)
        value = _answer_from_parsed(parsed)
        if value is not None:
            return value

    cleaned = strip_think_blocks(text)

    answer_patterns = [
        r"^\s*FINAL_ANSWER\s*:\s*(.+?)\s*$",
        r"^\s*Final\s+Answer\s*:\s*(.+?)\s*$",
        r"^\s*final\s+answer\s+is\s+(.+?)\s*$",
        r"^\s*Answer\s*:\s*(.+?)\s*$",
    ]

    for pattern in answer_patterns:
        match = re.search(pattern, cleaned, flags=re.I | re.M)
        if match:
            value = _normalized_non_empty_answer(match.group(1))
            if value is not None:
                return value

    boxed = _normalized_non_empty_answer(extract_boxed(text or ""))
    if boxed is not None:
        return boxed

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if lines:
        last_line = lines[-1]
        looks_like_explanation = re.search(
            r"\b(therefore|because|hence|since|so|we|the answer|final answer|solution)\b",
            last_line,
            flags=re.I,
        )
        if len(last_line) <= 80 and looks_like_explanation is None:
            return _normalized_non_empty_answer(last_line)

    return None


def usage_total_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0

    for key in ["total_tokens", "total", "tokens"]:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)

    total = 0
    for key in ["prompt_tokens", "completion_tokens", "reasoning_tokens"]:
        value = usage.get(key)
        if isinstance(value, int):
            total += value
        elif isinstance(value, float):
            total += int(value)

    return total


def usage_prompt_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0

    value = usage.get("prompt_tokens")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def usage_completion_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0

    value = usage.get("completion_tokens")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def sum_usage(items: list[dict[str, Any]]) -> dict[str, int]:
    prompt = 0
    completion = 0
    total = 0

    for item in items:
        usage = item.get("usage")
        prompt += usage_prompt_tokens(usage)
        completion += usage_completion_tokens(usage)
        total += usage_total_tokens(usage)

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def call_llm(client, prompt: str, temperature: float) -> dict[str, Any]:
    started = time.perf_counter()

    result = call_chat_completion(
        client,
        prompt,
        temperature=temperature,
        max_tokens=MAX_TOKENS,
    )

    ended = time.perf_counter()

    result["wall_time_seconds"] = ended - started
    return result


def fallback_diagnostic(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostic = {
        "diagnosis": "The previous answer was incorrect, but no reliable diagnostic was extracted.",
        "likely_error_type": "unknown",
        "banned_assumption": "",
        "must_check": [],
        "next_strategy_hint": "Solve from a different approach and explicitly check all constraints.",
    }
    if extra:
        diagnostic.update(extra)
    return diagnostic


def normalize_diagnostic(parsed: dict[str, Any] | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return fallback_diagnostic(extra)

    allowed_error_types = {
        "misread_condition",
        "algebra_error",
        "invariant_error",
        "boundary_case_error",
        "format_error",
        "repeated_answer",
        "unknown",
    }
    likely_error_type = str(parsed.get("likely_error_type") or "unknown").strip()
    if likely_error_type not in allowed_error_types:
        likely_error_type = "unknown"

    must_check = parsed.get("must_check")
    if not isinstance(must_check, list):
        must_check = []
    must_check = [
        short_text(item, 160)
        for item in must_check
        if str(item or "").strip()
    ][:3]

    diagnostic = {
        "diagnosis": short_text(parsed.get("diagnosis") or fallback_diagnostic()["diagnosis"], 700),
        "likely_error_type": likely_error_type,
        "banned_assumption": short_text(parsed.get("banned_assumption") or "", 300),
        "must_check": must_check,
        "next_strategy_hint": short_text(
            parsed.get("next_strategy_hint") or fallback_diagnostic()["next_strategy_hint"],
            300,
        ),
    }
    if extra:
        diagnostic.update(extra)
    return diagnostic


def wrong_record_reason(wrong_record: dict[str, Any] | None) -> str:
    if not isinstance(wrong_record, dict):
        return ""

    parsed = wrong_record.get("parsed") or {}
    reason = (
        parsed.get("reason")
        or wrong_record.get("reason")
        or parsed.get("strategy")
        or parsed.get("used_context")
        or ""
    )
    return short_text(reason, 700)


def build_diagnostic_prompt(
    case: dict[str, Any],
    wrong_answer: str | None,
    wrong_record: dict[str, Any] | None,
    rejected_answers: list[str | None],
    method_name: str,
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    wrong_reason = wrong_record_reason(wrong_record)
    rejected_text = "\n".join(
        f"- {answer}"
        for answer in rejected_answers
        if normalize_answer(answer) is not None
    ) or "No previous rejected answers."

    return f"""
You are a diagnostic critic for an oracle-feedback math repair benchmark.

The gold answer is NOT provided. Do not guess or reveal the final answer.

You only know that the submitted answer below was marked incorrect by an oracle.
Your job is to diagnose likely failure modes and provide constraints for the next attempt.

Return ONLY a JSON object. Do not write markdown. Do not output the final answer.
The diagnosis must be at most 120 words. must_check must contain at most 3 items.

Required JSON format:
{{
  "diagnosis": "...",
  "likely_error_type": "misread_condition | algebra_error | invariant_error | boundary_case_error | format_error | repeated_answer | unknown",
  "banned_assumption": "...",
  "must_check": ["...", "..."],
  "next_strategy_hint": "..."
}}

Method:
{method_name}

Answer type:
{answer_type}

Wrong submitted answer:
{wrong_answer}

Wrong attempt strategy/reason:
{wrong_reason}

Previous rejected answers:
{rejected_text}

Oracle feedback:
incorrect

Problem:
{problem}
"""


def run_diagnostic_critic(
    client,
    case: dict[str, Any],
    wrong_answer: str | None,
    wrong_record: dict[str, Any] | None,
    rejected_answers: list[str | None],
    method_name: str,
) -> dict[str, Any]:
    prompt = build_diagnostic_prompt(
        case=case,
        wrong_answer=wrong_answer,
        wrong_record=wrong_record,
        rejected_answers=rejected_answers,
        method_name=method_name,
    )
    started = time.perf_counter()
    result = call_chat_completion(
        client,
        prompt,
        temperature=DIAG_TEMPERATURE,
        max_tokens=DIAG_MAX_TOKENS,
    )
    ended = time.perf_counter()
    result["wall_time_seconds"] = ended - started

    if result.get("error") is not None or result.get("finish_reason") == "api_error":
        return fallback_diagnostic({
            "parsed": None,
            "raw_output": result.get("content", ""),
            "finish_reason": result.get("finish_reason"),
            "usage": result.get("usage"),
            "api_call": True,
            "error": result.get("error"),
            "wall_time_seconds": result.get("wall_time_seconds"),
        })

    parsed = extract_json_object(result.get("content"))
    diagnostic = normalize_diagnostic(parsed, {
        "parsed": parsed,
        "raw_output": result.get("content", ""),
        "finish_reason": result.get("finish_reason"),
        "usage": result.get("usage"),
        "api_call": True,
        "error": None,
        "wall_time_seconds": result.get("wall_time_seconds"),
    })
    return diagnostic


def should_include_case(case: dict[str, Any]) -> bool:
    if not ONLY_LOW_CONF:
        return True

    support = to_int(case.get("raw_selected_support"), 0)
    return support <= LOW_CONF_MAX_SUPPORT


def parse_case_ids_from_env() -> set[int] | None:
    raw = os.getenv("FEEDBACK_CASE_IDS", "").strip()

    if not raw:
        return None

    case_ids = set()

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        case_ids.add(int(item))

    return case_ids or None


def get_case_identity(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case.get("id"),
        "question_id": case.get("question_id"),
        "answer_type": case.get("answer_type"),
        "problem": case.get("problem"),
        "gold": case.get("gold"),
        "raw_selected_answer": normalize_answer(case.get("raw_selected_answer")),
        "raw_selected_support": case.get("raw_selected_support"),
        "raw_correct": case.get("raw_correct"),
        "oracle_correct": case.get("oracle_correct"),
    }


def normalized_wrong_answers(attempts: list[dict[str, Any]], answer_key: str = "answer") -> list[str]:
    wrong = []

    for attempt in attempts:
        if attempt.get("correct") is True:
            continue

        answer = normalize_answer(attempt.get(answer_key))
        if answer is not None:
            wrong.append(answer)

    return wrong


def answer_in_list(answer: str | None, answer_list: list[str | None]) -> bool:
    answer = normalize_answer(answer)

    if answer is None:
        return False

    for candidate in answer_list:
        candidate = normalize_answer(candidate)
        if candidate is None:
            continue

        if answer == candidate:
            return True

        if equivalent(answer, candidate):
            return True

    return False


def is_valid_answer(answer: str | None) -> bool:
    answer = normalize_answer(answer)

    if answer is None:
        return False

    invalid_values = {
        "none",
        "null",
        "n/a",
        "na",
        "no answer",
        "no_answer",
        "cannot determine",
        "empty",
        "unknown",
        "unparseable",
        "invalid",
    }

    return answer.lower().strip() not in invalid_values


def filter_valid_non_rejected_clusters(
    clusters: list[dict[str, Any]],
    rejected_answers: list[str | None],
) -> list[dict[str, Any]]:
    filtered = []

    for cluster in clusters:
        answer = normalize_answer(cluster.get("canonical_answer"))

        if not is_valid_answer(answer):
            continue

        if answer_in_list(answer, rejected_answers):
            continue

        filtered.append(cluster)

    return filtered


def make_forbidden_answers_text(attempts: list[dict[str, Any]]) -> str:
    forbidden_answers = normalized_wrong_answers(attempts, "answer")

    if not forbidden_answers:
        return "No forbidden answers yet."

    lines = []
    for i, answer in enumerate(forbidden_answers, start=1):
        lines.append(f"{i}. {answer}")

    return "\n".join(lines)


def get_rejected_answers_from_shared_context(shared_context: dict[str, Any]) -> list[str]:
    rejected_answers = []

    for item in shared_context.get("rejected_answers", []):
        if isinstance(item, dict):
            answer = normalize_answer(item.get("answer"))
        else:
            answer = normalize_answer(item)

        if answer is not None:
            rejected_answers.append(answer)

    return rejected_answers


def repeated_wrong_answer_count(wrong_answers: list[str]) -> int:
    counts = Counter(wrong_answers)
    return sum(count - 1 for count in counts.values() if count > 1)


def is_truncated_answer_item(item: dict[str, Any]) -> bool:
    return item.get("finish_reason") == "length"


def is_parser_invalid_item(item: dict[str, Any]) -> bool:
    parser_debug = item.get("parser_debug") or {}
    return bool(item.get("raw_output")) and parser_debug.get("extracted_answer") is None


def invalid_metric_counts(items: list[dict[str, Any]], invalid_key: str) -> dict[str, int]:
    invalid_items = [
        item for item in items
        if item.get(invalid_key) is True
    ]
    truncated_items = [
        item for item in invalid_items
        if is_truncated_answer_item(item)
    ]
    parser_invalid_items = [
        item for item in invalid_items
        if not is_truncated_answer_item(item) and is_parser_invalid_item(item)
    ]

    return {
        "invalid_answer_count": len(invalid_items),
        "truncated_answer_count": len(truncated_items),
        "parser_invalid_count": len(parser_invalid_items),
    }


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


def build_main_agent_prompt(
    case: dict[str, Any],
    round_id: int,
    attempts: list[dict[str, Any]],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    previous_attempts = make_previous_attempts_text(attempts)
    diagnostic_history = make_diagnostic_history_text(attempts)
    forbidden_answers_text = make_forbidden_answers_text(attempts)
    round_strategy = STRATEGY_POOL[(round_id - 1) % len(STRATEGY_POOL)]

    return f"""
You are a single centralized math-solving agent.

The gold answer is NOT provided.

You are solving a hard olympiad-style math problem under oracle-feedback retry.
After each wrong attempt, the only feedback you receive is that your previous final answer was incorrect.
You must use that feedback to avoid repeating the same answer or same flawed route.

Important rules:
- Do not repeat any previous wrong final answer.
- final_answer must be a concrete answer, not empty, missing, placeholder, or unparsable.
- If previous attempts failed, change strategy substantially.
- You must not reuse any banned assumption from diagnostic feedback.
- You must explicitly address the must_check items before choosing final_answer.
- If your final_answer is equivalent to any forbidden answer, your response is invalid.
- You must change both the final answer and the solution strategy.
- Do not merely rephrase a previous failed solution.
- In this round, use the assigned strategy.
- Check answer format for the expected answer type.
- Output ONLY the JSON object. Do not write markdown, prose, or code fences.
- The JSON object must begin at the first character of your response.
- Do not write anything before the JSON object.
- Do not output <think> tags, hidden reasoning, derivation paragraphs, or long analysis.
- strategy must be at most 1 sentence.
- reason must be at most 2 sentences.
- Your entire response must be under 250 words.

Required JSON format:
{{
  "final_answer": "your final answer",
  "strategy": "one sentence maximum",
  "reason": "two sentences maximum",
  "confidence": 0-100,
  "changed_from_previous_attempts": true
}}

Answer type:
{answer_type}

Current round:
{round_id}

Assigned strategy for this round:
{round_strategy}

CRITICAL FORBIDDEN ANSWERS:
The following answers are already known to be incorrect.
You must not output any answer equivalent to them.

{forbidden_answers_text}

Previous wrong attempts:
{previous_attempts}

DIAGNOSTIC FEEDBACK FROM PREVIOUS FAILURES:
{diagnostic_history}

Problem:
{problem}
"""


def run_main_agent_feedback_retry(client, case: dict[str, Any]) -> dict[str, Any] | None:
    if USE_RAW_INIT and case_raw_correct(case) is True:
        return raw_vote_already_correct_main_result(case)

    started = time.perf_counter()
    attempts = []
    solved = False
    final_answer = None
    stop_reason = "max_rounds_reached"

    if USE_RAW_INIT and case_raw_correct(case) is False:
        attempts.append(make_raw_vote_seed_attempt(case))

    for round_id in range(1, MAX_ROUNDS + 1):
        print(f"--- Main-Agent round {round_id}/{MAX_ROUNDS} ---")

        prompt = build_main_agent_prompt(case, round_id, attempts)
        result = call_llm(client, prompt, temperature=TEMPERATURE)

        if result.get("error") is not None or result.get("finish_reason") == "api_error":
            append_jsonl(ERROR_PATH, {
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
                "use_strict_equiv": USE_STRICT_EQUIV,
            }
        elif duplicate_forbidden:
            correct = False
            oracle_feedback = "incorrect_repeated_forbidden_answer"
            verification = {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": USE_STRICT_EQUIV,
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

        if USE_DIAGNOSTIC and oracle_feedback == "incorrect":
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

        time.sleep(SLEEP_SECONDS)

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


def make_shared_context_text(shared_context: dict[str, Any]) -> str:
    safe_context = {
        "rejected_answers": shared_context.get("rejected_answers", []),
        "failed_attempt_summaries": shared_context.get("failed_attempt_summaries", []),
        "round_notes": shared_context.get("round_notes", []),
        "diagnostics": shared_context.get("diagnostics", []),
        "banned_assumptions": shared_context.get("banned_assumptions", []),
        "must_check_items": shared_context.get("must_check_items", []),
        "strategy_hints": shared_context.get("strategy_hints", []),
        "verified_notes": shared_context.get("verified_notes", []),
        "note_admission_log": shared_context.get("note_admission_log", [])[-8:],
    }

    return json.dumps(safe_context, ensure_ascii=False, indent=2)


def make_shared_diagnostic_feedback_text(shared_context: dict[str, Any]) -> str:
    banned_assumptions = shared_context.get("banned_assumptions", []) or []
    must_check_items = shared_context.get("must_check_items", []) or []
    strategy_hints = shared_context.get("strategy_hints", []) or []

    return "\n".join([
        "banned assumptions:",
        *(f"- {item}" for item in banned_assumptions),
        "must-check items:",
        *(f"- {item}" for item in must_check_items),
        "strategy hints:",
        *(f"- {item}" for item in strategy_hints),
    ])


TASK_QUEUE_ROLES = [
    "numeric_checker",
    "symbolic_solver",
    "boundary_checker",
    "final_integrator",
]


def get_worker_role(worker_id: int) -> str:
    if not USE_TASK_QUEUE:
        return "general_solver"
    if TASK_QUEUE_MODE != "static":
        return "general_solver"
    return TASK_QUEUE_ROLES[worker_id % len(TASK_QUEUE_ROLES)]


def make_verified_notes_text(shared_context: dict[str, Any]) -> str:
    return format_verified_notes(shared_context.get("verified_notes", []))


def build_delm_worker_prompt(
    case: dict[str, Any],
    round_id: int,
    worker_id: int,
    shared_context: dict[str, Any],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    worker_role = get_worker_role(worker_id)
    strategy = STRATEGY_POOL[(round_id + worker_id - 1) % len(STRATEGY_POOL)]
    context_text = make_shared_context_text(shared_context)
    diagnostic_feedback_text = make_shared_diagnostic_feedback_text(shared_context)
    verified_notes_text = make_verified_notes_text(shared_context)

    return f"""
You are worker_{worker_id} in a DELM-lite feedback-repair system.

The gold answer is NOT provided.

You receive a compact shared context from previous rounds.
The shared context may contain rejected final answers. These answers were submitted to an oracle and marked incorrect.
Your job is to propose a new candidate answer while avoiding repeated mistakes.

Important rules:
- Do not output any answer listed in rejected_answers.
- Must propose an answer that avoids all rejected answers.
- Must not rely on banned assumptions.
- Must explicitly use at least one strategy hint if available.
- Use a substantially different route if previous attempts failed.
- Follow your assigned strategy, but prioritize correctness.
- Check the answer format for the expected answer type.
- candidate_answer must be a concrete answer, not empty, missing, placeholder, or unparsable.
- Put candidate_answer first in the JSON object. Do not write any reasoning before it.
- Output at most 2 intermediate_claims.
- Each claim must be at most 120 characters.
- Each evidence field must be at most 180 characters.
- Do not label guesses, "I think", "maybe", or "probably" as FACT.
- If a claim is speculative, label it STRATEGY or CANDIDATE_SUPPORT, not FACT.
- If you use a verified note, explicitly cite its note_id in evidence or reason.
- For set answers, label each note using metadata.set_support_subtype:
  membership_evidence for one value in the set, exclusion_evidence for one impossible value,
  completeness_evidence only when you prove the whole set is complete.
- Finite checks such as n=0..120 are partial_enumeration, not completeness_evidence.
- Diagnostics are hints, not verified facts.
- Verified notes are shared facts admitted by the system; you may rely on them.
- If a verified note contradicts your reasoning, address it explicitly.
- Output ONLY the JSON object. Do not write markdown, prose, or code fences.
- The JSON object must begin at the first character of your response.
- Do not write anything before the JSON object.
- Do not output <think> tags, hidden reasoning, derivation paragraphs, or long analysis.
- strategy must be at most 1 sentence.
- reason must be at most 2 sentences.
- Your entire response must be under 180 words.

Required JSON format:
{{
  "candidate_answer": "your candidate final answer",
  "strategy": "one sentence maximum",
  "reason": "two sentences maximum",
  "confidence": 0-100,
  "intermediate_claims": [
    {{
      "type": "FACT | FAIL | NUMERIC_CHECK | SYMBOLIC_CHECK | BOUND | ENUMERATION | STRATEGY | CANDIDATE_SUPPORT",
      "claim": "max 120 chars; short checkable conclusion",
      "evidence": "max 180 chars; cite note_id if used",
      "check_method": "none | sympy_simplify | numeric_eval | small_case_enumeration | llm_admission",
      "supports_answer": "optional answer this supports",
      "blocks_answer": "optional answer this blocks",
      "metadata": {{"set_support_subtype": "membership_evidence | exclusion_evidence | completeness_evidence | partial_enumeration"}}
    }}
  ]
}}

Answer type:
{answer_type}

Round:
{round_id}

Worker id:
{worker_id}

Worker role:
{worker_role}

Role guidance:
- numeric_checker: prioritize 1-2 NUMERIC_CHECK notes with directly checkable claims such as `expression = value`, `polynomial_value_at_candidate = 0`, `candidate_numeric_value = 6`, or `strict_equiv(candidate, rejected_answer) = False`; do not guess complex formulas.
- For set/enumeration problems, numeric_checker should output finite checks like `n=0..120 values = {{0,2,4,...}}` with check_method `small_case_enumeration`.
- symbolic_solver: prioritize FACT / SYMBOLIC_CHECK / CANDIDATE_SUPPORT notes.
- boundary_checker: prioritize BOUND / FAIL notes and edge cases.
- final_integrator: synthesize verified notes into the candidate answer.

Assigned strategy:
{strategy}

VERIFIED SHARED NOTES:
{verified_notes_text}

Shared context:
{context_text}

SHARED DIAGNOSTIC FEEDBACK:
{diagnostic_feedback_text}

Problem:
{problem}
"""


def build_delm_selector_prompt(
    case: dict[str, Any],
    round_id: int,
    shared_context: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    context_text = make_shared_context_text(shared_context)

    worker_lines = []
    for output in worker_outputs:
        parsed = output.get("parsed") or {}
        worker_lines.append(
            json.dumps(
                {
                    "worker_id": output.get("worker_id"),
                    "answer": output.get("answer"),
                    "strategy": parsed.get("strategy"),
                    "reason": parsed.get("reason"),
                    "confidence": parsed.get("confidence"),
                },
                ensure_ascii=False,
            )
        )

    cluster_lines = []
    for cluster in clusters:
        cluster_lines.append(
            json.dumps(
                {
                    "cluster_id": cluster.get("cluster_id"),
                    "canonical_answer": cluster.get("canonical_answer"),
                    "support_count": cluster.get("support_count"),
                    "members": cluster.get("members"),
                },
                ensure_ascii=False,
            )
        )

    return f"""
You are the selector in a DELM-lite feedback-repair system.

The gold answer is NOT provided.

You receive:
1. The original problem.
2. A shared context containing previously rejected final answers.
3. Candidate answers proposed by worker agents in the current round.
4. Candidate clusters.

Your task:
- Select exactly one answer to submit to the oracle for this round.
- Do not select an answer that appears in rejected_answers.
- Prefer answers with concrete reasoning and consistency with the problem constraints.
- Do not invent a new answer unless every candidate is invalid or unparsable.
- Output ONLY the JSON object. Do not write markdown, prose, or code fences.
- The JSON object must begin at the first character of your response.
- Do not write anything before the JSON object.
- Do not output <think> tags, hidden reasoning, derivation paragraphs, or long analysis.
- reason must be at most 1 sentence.
- Your entire response must be under 250 words.

Required JSON format:
{{
  "selected_cluster_id": 0,
  "selected_answer": "the answer to submit",
  "reason": "one sentence maximum",
  "confidence": 0-100
}}

Answer type:
{answer_type}

Round:
{round_id}

Shared context:
{context_text}

Problem:
{problem}

Worker outputs:
{chr(10).join(worker_lines)}

Candidate clusters:
{chr(10).join(cluster_lines)}
"""


def parse_selected_cluster_id(parsed: dict[str, Any] | None, text: str | None = None) -> int | None:
    if parsed:
        for key in ["selected_cluster_id", "cluster_id"]:
            cid = to_int(parsed.get(key), None)
            if cid is not None:
                return cid

    if text:
        patterns = [
            r"selected_cluster_id[\"']?\s*[:=]\s*(\d+)",
            r"Selected\s*Cluster\s*:\s*(\d+)",
            r"Cluster\s*:\s*(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return to_int(match.group(1), None)

    return None


def get_cluster_by_id(clusters: list[dict[str, Any]], cid: int | None) -> dict[str, Any] | None:
    if cid is None:
        return None

    for cluster in clusters:
        if to_int(cluster.get("cluster_id"), None) == cid:
            return cluster

    return None


def make_worker_confidence_map(worker_outputs: list[dict[str, Any]]) -> dict[int, float]:
    confidences = {}

    for output in worker_outputs:
        worker_id = to_int(output.get("worker_id"), None)
        if worker_id is None:
            continue

        parsed = output.get("parsed") or {}
        confidences[worker_id] = to_float(parsed.get("confidence"), 0.0)

    return confidences


def note_answer_matches(note_answer: str | None, candidate_answer: str | None) -> bool:
    note_answer = normalize_answer(note_answer)
    candidate_answer = normalize_answer(candidate_answer)
    if note_answer is None or candidate_answer is None:
        return False
    strict_result = strict_equivalence_check(note_answer, candidate_answer) if USE_STRICT_EQUIV else None
    if strict_result is not None:
        return strict_result
    return answer_equiv(note_answer, candidate_answer)


def verified_note_answer_counts(
    candidate_answer: str | None,
    shared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_set = parse_integer_set(candidate_answer or "")
    if candidate_set is not None:
        return verified_set_note_answer_counts(candidate_answer, shared_context)

    support_ids = []
    block_ids = []

    for note in ((shared_context or {}).get("verified_notes", []) or []):
        if note.get("status") != "verified":
            continue
        if note_answer_matches(note.get("supports_answer"), candidate_answer):
            support_ids.append(note.get("note_id"))
        if note_answer_matches(note.get("blocks_answer"), candidate_answer):
            block_ids.append(note.get("note_id"))

    return {
        "verified_support_count": len(support_ids),
        "verified_block_count": len(block_ids),
        "supporting_note_ids": support_ids,
        "blocking_note_ids": block_ids,
    }


def _metadata_int_set(metadata: dict[str, Any], key: str) -> set[int]:
    values = metadata.get(key)
    if not isinstance(values, list):
        return set()
    out = set()
    for value in values:
        try:
            out.add(int(value))
        except Exception:
            continue
    return out


def verified_set_note_answer_counts(
    candidate_answer: str | None,
    shared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_set = parse_integer_set(candidate_answer or "")
    if candidate_set is None:
        return {
            "verified_support_count": 0,
            "verified_block_count": 0,
            "supporting_note_ids": [],
            "blocking_note_ids": [],
            "membership_values_verified": [],
            "completeness_evidence_present": False,
            "missing_verified_members": [],
            "extra_unverified_members": [],
            "set_support_type": "none",
        }

    support_ids = []
    block_ids = []
    membership_values = set()
    completeness_evidence_present = False
    complete_value_sets = []

    for note in ((shared_context or {}).get("verified_notes", []) or []):
        if note.get("status") != "verified":
            continue

        metadata = note.get("metadata") if isinstance(note.get("metadata"), dict) else {}
        subtype = str(metadata.get("set_support_subtype") or "").strip()
        note_id = note.get("note_id")

        if subtype == "completeness_evidence":
            completeness_evidence_present = True
            value_set = _metadata_int_set(metadata, "value_set")
            if not value_set:
                parsed_set = parse_integer_set(note.get("supports_answer") or "")
                value_set = parsed_set or set()

            if metadata.get("complete") is True and value_set:
                complete_value_sets.append(value_set)
                if value_set == candidate_set:
                    support_ids.append(note_id)
                else:
                    block_ids.append(note_id)
            continue

        if subtype == "exclusion_evidence":
            excluded_values = _metadata_int_set(metadata, "excluded_values")
            excluded_value = parse_integer_value(note.get("blocks_answer"))
            if excluded_value is not None:
                excluded_values.add(excluded_value)
            if excluded_values & candidate_set:
                block_ids.append(note_id)
            continue

        note_members = _metadata_int_set(metadata, "membership_values")
        if not note_members:
            support_value = parse_integer_value(note.get("supports_answer"))
            if support_value is not None:
                note_members.add(support_value)
        if not note_members:
            value_set = _metadata_int_set(metadata, "value_set")
            if subtype in {"membership_evidence", "partial_enumeration"}:
                note_members.update(value_set)

        if note_members:
            membership_values.update(note_members)
            if note_members - candidate_set:
                block_ids.append(note_id)

    missing_verified_members = sorted(membership_values - candidate_set)
    extra_unverified_members = sorted(candidate_set - membership_values) if membership_values else sorted(candidate_set)

    if support_ids:
        set_support_type = "complete"
    elif membership_values:
        set_support_type = "partial"
    else:
        set_support_type = "none"

    return {
        "verified_support_count": len(support_ids),
        "verified_block_count": len([note_id for note_id in block_ids if note_id is not None]),
        "supporting_note_ids": [note_id for note_id in support_ids if note_id is not None],
        "blocking_note_ids": [note_id for note_id in block_ids if note_id is not None],
        "membership_values_verified": sorted(membership_values),
        "completeness_evidence_present": completeness_evidence_present,
        "missing_verified_members": missing_verified_members,
        "extra_unverified_members": extra_unverified_members,
        "set_support_type": set_support_type,
    }


def score_cluster(
    cluster: dict[str, Any],
    worker_confidences: dict[int, float],
    shared_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    member_confidences = []

    for member in cluster.get("members", []):
        worker_id = to_int(member.get("worker_id"), None)
        if worker_id is not None and worker_id in worker_confidences:
            member_confidences.append(worker_confidences[worker_id])

    support_count = to_int(cluster.get("support_count"), None)
    if support_count is None:
        support_count = len(cluster.get("members", []))

    avg_confidence = (
        sum(member_confidences) / len(member_confidences)
        if member_confidences else 0.0
    )
    max_confidence = max(member_confidences) if member_confidences else 0.0

    note_counts = verified_note_answer_counts(cluster.get("canonical_answer"), shared_context)

    return {
        "cluster_id": cluster.get("cluster_id"),
        "canonical_answer": cluster.get("canonical_answer"),
        "support_count": support_count,
        "avg_confidence": avg_confidence,
        "max_confidence": max_confidence,
        "member_worker_ids": [
            to_int(member.get("worker_id"), None)
            for member in cluster.get("members", [])
            if to_int(member.get("worker_id"), None) is not None
        ],
        **note_counts,
    }


def deterministic_cluster_sort_key(score: dict[str, Any]) -> tuple[int, int, int, float, float, int]:
    cluster_id = to_int(score.get("cluster_id"), None)
    if cluster_id is None:
        cluster_id = 10**9

    return (
        to_int(score.get("verified_block_count"), 0) or 0,
        -(to_int(score.get("verified_support_count"), 0) or 0),
        -(to_int(score.get("support_count"), 0) or 0),
        -to_float(score.get("avg_confidence"), 0.0),
        -to_float(score.get("max_confidence"), 0.0),
        cluster_id,
    )


def final_selector_sort_key(score: dict[str, Any]) -> tuple[int, int, int, float, float, float, int]:
    cluster_id = to_int(score.get("cluster_id"), None)
    if cluster_id is None:
        cluster_id = 10**9

    return (
        to_int(score.get("verified_block_count"), 0) or 0,
        -(to_int(score.get("verified_support_count"), 0) or 0),
        -(to_int(score.get("support_count"), 0) or 0),
        -to_float(score.get("avg_confidence"), 0.0),
        -to_float(score.get("adjusted_verifier_score"), 0.0),
        -to_float(score.get("max_confidence"), 0.0),
        cluster_id,
    )


def with_final_selection_score(
    score: dict[str, Any],
    verifier_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verifier_score = (
        to_float(verifier_evaluation.get("score"), 0.0)
        if isinstance(verifier_evaluation, dict)
        else to_float(score.get("verifier_score"), 0.0)
    )
    verified_support_count = to_int(score.get("verified_support_count"), 0) or 0
    verifier_verdict = (
        verifier_evaluation.get("verdict")
        if isinstance(verifier_evaluation, dict)
        else score.get("verifier_verdict")
    )
    unsupported_verifier_accept = (
        verifier_verdict == "accept"
        and verified_support_count == 0
    )
    adjusted_verifier_score = verifier_score
    if unsupported_verifier_accept:
        adjusted_verifier_score = min(adjusted_verifier_score, 50.0)

    out = {
        **score,
        "verifier_score": verifier_score,
        "adjusted_verifier_score": adjusted_verifier_score,
        "verifier_verdict": verifier_verdict,
        "unsupported_verifier_accept": unsupported_verifier_accept,
    }
    out["final_selection_score"] = {
        "verified_block_count": out.get("verified_block_count", 0),
        "verified_support_count": out.get("verified_support_count", 0),
        "verifier_score": verifier_score,
        "adjusted_verifier_score": adjusted_verifier_score,
        "unsupported_verifier_accept": unsupported_verifier_accept,
        "set_support_type": out.get("set_support_type"),
        "missing_verified_members": out.get("missing_verified_members"),
        "extra_unverified_members": out.get("extra_unverified_members"),
        "support_count": out.get("support_count", 0),
        "avg_confidence": out.get("avg_confidence", 0.0),
        "max_confidence": out.get("max_confidence", 0.0),
        "cluster_id": out.get("cluster_id"),
    }
    return out


def enrich_cluster_scores_with_verifier(
    cluster_scores: list[dict[str, Any]],
    verifier_evaluations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    evaluations_by_id = {
        evaluation.get("cluster_id"): evaluation
        for evaluation in (verifier_evaluations or [])
        if isinstance(evaluation, dict)
    }
    return [
        with_final_selection_score(score, evaluations_by_id.get(score.get("cluster_id")))
        for score in cluster_scores
    ]


def worker_output_by_id(worker_outputs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out = {}

    for output in worker_outputs:
        worker_id = to_int(output.get("worker_id"), None)
        if worker_id is not None:
            out[worker_id] = output

    return out


def cluster_worker_evidence(
    cluster: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    outputs_by_id = worker_output_by_id(worker_outputs)
    evidence = []

    for member in cluster.get("members", []):
        worker_id = to_int(member.get("worker_id"), None)
        output = outputs_by_id.get(worker_id)
        if output is None:
            continue
        parsed = output.get("parsed") or {}
        evidence.append({
            "worker_id": worker_id,
            "answer": output.get("answer"),
            "strategy": parsed.get("strategy"),
            "reason": parsed.get("reason"),
            "confidence": parsed.get("confidence"),
        })

    return evidence


def build_candidate_verifier_prompt(
    case: dict[str, Any],
    cluster: dict[str, Any],
    cluster_score: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    shared_context: dict[str, Any],
    rejected_answers: list[str | None],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    candidate_answer = normalize_answer(cluster.get("canonical_answer"))
    rejected_text = "\n".join(
        f"- {answer}"
        for answer in rejected_answers
        if normalize_answer(answer) is not None
    ) or "No rejected answers."
    diagnostics_text = json.dumps(
        {
            "diagnostics": shared_context.get("diagnostics", []),
            "banned_assumptions": shared_context.get("banned_assumptions", []),
            "must_check_items": shared_context.get("must_check_items", []),
            "strategy_hints": shared_context.get("strategy_hints", []),
            "verified_notes": shared_context.get("verified_notes", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    worker_evidence = json.dumps(
        cluster_worker_evidence(cluster, worker_outputs),
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are a candidate verifier for a math feedback-repair benchmark.

The gold answer is NOT provided. Do not guess or reveal the final answer.
Evaluate only the given candidate answer. Do not generate a new answer.

A simple answer can be correct. Do not prefer complex-looking answers. Judge only by whether the candidate follows from the problem and addresses diagnostics.

Return ONLY a JSON object. Do not write markdown.
The reason must be one concise sentence.

Required JSON format:
{{
  "candidate_answer": "{candidate_answer}",
  "verdict": "accept | reject | uncertain",
  "score": 0-100,
  "reason": "one concise sentence",
  "violated_rejected_answer": false,
  "uses_banned_assumption": false,
  "addresses_must_check": true
}}

Answer type:
{answer_type}

Candidate cluster:
{json.dumps(cluster_score, ensure_ascii=False, indent=2)}

Candidate worker evidence:
{worker_evidence}

Previous rejected answers:
{rejected_text}

Diagnostic feedback:
{diagnostics_text}

Problem:
{problem}
"""


def normalize_verifier_evaluation(
    parsed: dict[str, Any] | None,
    cluster_score: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        parsed = {}

    verdict = str(parsed.get("verdict") or "uncertain").strip().lower()
    if verdict not in {"accept", "reject", "uncertain"}:
        verdict = "uncertain"

    score = to_float(parsed.get("score"), 0.0)
    if score < 0:
        score = 0.0
    if score > 100:
        score = 100.0

    return {
        "cluster_id": cluster_score.get("cluster_id"),
        "candidate_answer": normalize_answer(parsed.get("candidate_answer"))
        or cluster_score.get("canonical_answer"),
        "support_count": cluster_score.get("support_count"),
        "avg_confidence": cluster_score.get("avg_confidence"),
        "max_confidence": cluster_score.get("max_confidence"),
        "member_worker_ids": cluster_score.get("member_worker_ids", []),
        "verified_support_count": cluster_score.get("verified_support_count", 0),
        "verified_block_count": cluster_score.get("verified_block_count", 0),
        "supporting_note_ids": cluster_score.get("supporting_note_ids", []),
        "blocking_note_ids": cluster_score.get("blocking_note_ids", []),
        "membership_values_verified": cluster_score.get("membership_values_verified", []),
        "completeness_evidence_present": cluster_score.get("completeness_evidence_present", False),
        "missing_verified_members": cluster_score.get("missing_verified_members", []),
        "extra_unverified_members": cluster_score.get("extra_unverified_members", []),
        "set_support_type": cluster_score.get("set_support_type", "none"),
        "verdict": verdict,
        "score": score,
        "reason": short_text(
            parsed.get("reason") or "No reliable verifier reason was extracted.",
            500,
        ),
        "violated_rejected_answer": bool(parsed.get("violated_rejected_answer")),
        "uses_banned_assumption": bool(parsed.get("uses_banned_assumption")),
        "addresses_must_check": bool(parsed.get("addresses_must_check")),
        "parsed": parsed if parsed else None,
        "raw_output": result.get("content", ""),
        "finish_reason": result.get("finish_reason"),
        "usage": result.get("usage"),
        "api_call": True,
        "error": result.get("error"),
        "wall_time_seconds": result.get("wall_time_seconds"),
    }


def run_candidate_verifier(
    client,
    case: dict[str, Any],
    cluster: dict[str, Any],
    cluster_score: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    shared_context: dict[str, Any],
    rejected_answers: list[str | None],
) -> dict[str, Any]:
    prompt = build_candidate_verifier_prompt(
        case=case,
        cluster=cluster,
        cluster_score=cluster_score,
        worker_outputs=worker_outputs,
        shared_context=shared_context,
        rejected_answers=rejected_answers,
    )
    started = time.perf_counter()
    result = call_chat_completion(
        client,
        prompt,
        temperature=VERIFIER_TEMPERATURE,
        max_tokens=VERIFIER_MAX_TOKENS,
    )
    ended = time.perf_counter()
    result["wall_time_seconds"] = ended - started

    parsed = None
    if result.get("error") is None and result.get("finish_reason") != "api_error":
        parsed = extract_json_object(result.get("content"))

    return normalize_verifier_evaluation(parsed, cluster_score, result)


def verifier_selection_sort_key(
    evaluation: dict[str, Any],
    score_by_id: dict[Any, dict[str, Any]],
) -> tuple[int, int, float, int, float, int]:
    cluster_id = evaluation.get("cluster_id")
    score = with_final_selection_score(score_by_id.get(cluster_id, {}), evaluation)
    return final_selector_sort_key(score)


def select_cluster_with_verifier(
    client,
    case: dict[str, Any],
    shared_context: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    cluster_scores: list[dict[str, Any]],
    rejected_answers: list[str | None],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], bool]:
    clusters_by_id = {
        score.get("cluster_id"): cluster
        for cluster, score in zip(clusters, cluster_scores)
    }
    score_by_id = {score.get("cluster_id"): score for score in cluster_scores}

    evaluations = []
    for score in cluster_scores:
        cluster = clusters_by_id.get(score.get("cluster_id"))
        if cluster is None:
            continue
        evaluations.append(run_candidate_verifier(
            client=client,
            case=case,
            cluster=cluster,
            cluster_score=score,
            worker_outputs=worker_outputs,
            shared_context=shared_context,
            rejected_answers=rejected_answers,
        ))

    selected_evaluation = sorted(
        evaluations,
        key=lambda evaluation: verifier_selection_sort_key(evaluation, score_by_id),
    )[0]
    selected_cluster = clusters_by_id.get(selected_evaluation.get("cluster_id")) or clusters[0]
    all_verifier_rejected = all(
        evaluation.get("verdict") == "reject"
        for evaluation in evaluations
    )

    return selected_cluster, selected_evaluation, evaluations, all_verifier_rejected


def build_worker_clusters(
    worker_outputs: list[dict[str, Any]],
    rejected_answers: list[str | None],
) -> list[dict[str, Any]]:
    valid_outputs = [
        output
        for output in worker_outputs
        if is_valid_answer(output.get("answer"))
        and not answer_in_list(output.get("answer"), rejected_answers)
    ]

    answers = [output.get("answer") for output in valid_outputs]

    if not answers:
        return []

    clusters = cluster_answers(answers)

    # 把 sample_id 映射回 worker_id，方便报告分析。
    for cluster in clusters:
        for member in cluster.get("members", []):
            sample_id = to_int(member.get("sample_id"), None)
            if sample_id is not None and 0 <= sample_id < len(valid_outputs):
                member["worker_id"] = valid_outputs[sample_id].get("worker_id")
                member["strategy"] = (valid_outputs[sample_id].get("parsed") or {}).get("strategy")

    return clusters


def make_note_admission_settings(client) -> dict[str, Any]:
    return {
        "client": client,
        "admission_max_tokens": ADMISSION_MAX_TOKENS,
        "admission_temperature": ADMISSION_TEMPERATURE,
        "use_llm_admission_fallback": USE_LLM_ADMISSION,
    }


def ensure_note_context(shared_context: dict[str, Any]) -> dict[str, Any]:
    shared_context.setdefault("verified_notes", [])
    shared_context.setdefault("rejected_notes", [])
    shared_context.setdefault("note_admission_log", [])
    return shared_context


def admit_round_worker_notes(
    client,
    case: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    shared_context: dict[str, Any],
) -> dict[str, Any]:
    ensure_note_context(shared_context)

    round_verified = []
    round_rejected = []
    round_admission_results = []
    admission_calls = 0
    admission_tokens = 0
    admission_evaluations = 0
    settings = make_note_admission_settings(client)

    for worker in worker_outputs:
        admission = admit_worker_claims(
            case=case,
            worker_record=worker,
            shared_context=shared_context,
            settings=settings,
        )
        worker["admission_results"] = admission.get("admission_results", [])
        worker["verified_notes_added"] = admission.get("verified_notes", [])
        worker["rejected_notes_added"] = admission.get("rejected_notes", [])

        for note in admission.get("verified_notes", []):
            shared_context["verified_notes"].append(note)
            round_verified.append(note)

        for note in admission.get("rejected_notes", []):
            shared_context["rejected_notes"].append(note)
            round_rejected.append(note)

        for result in admission.get("admission_results", []):
            shared_context["note_admission_log"].append({
                "round": worker.get("round"),
                "worker_id": worker.get("worker_id"),
                "note_id": (result.get("note") or {}).get("note_id"),
                "status": result.get("status"),
                "reason": result.get("reason"),
                "duplicate_verified_note": result.get("duplicate_verified_note"),
            })
            round_admission_results.append(result)

        admission_calls += to_int(admission.get("admission_calls"), 0) or 0
        admission_tokens += to_int(admission.get("admission_tokens"), 0) or 0
        admission_evaluations += to_int(admission.get("admission_evaluations"), 0) or 0

    return {
        "verified_notes": round_verified,
        "rejected_notes": round_rejected,
        "admission_results": round_admission_results,
        "admission_evaluations": admission_evaluations,
        "admission_calls": admission_calls,
        "admission_tokens": admission_tokens,
    }


def run_delm_workers(
    client,
    case: dict[str, Any],
    round_id: int,
    shared_context: dict[str, Any],
) -> list[dict[str, Any]] | None:
    outputs = []
    rejected_answers = get_rejected_answers_from_shared_context(shared_context)

    for worker_id in range(DELM_WORKERS):
        worker_role = get_worker_role(worker_id)
        print(f"--- DELM worker {worker_id}, round {round_id}/{MAX_ROUNDS} ---")

        prompt = build_delm_worker_prompt(
            case=case,
            round_id=round_id,
            worker_id=worker_id,
            shared_context=shared_context,
        )

        result = call_llm(client, prompt, temperature=TEMPERATURE)

        if result.get("error") is not None or result.get("finish_reason") == "api_error":
            append_jsonl(ERROR_PATH, {
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
                "use_strict_equiv": USE_STRICT_EQUIV,
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

        time.sleep(SLEEP_SECONDS)

    return outputs


def run_delm_selector(
    client,
    case: dict[str, Any],
    round_id: int,
    shared_context: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    rejected_answers = get_rejected_answers_from_shared_context(shared_context)
    clusters = filter_valid_non_rejected_clusters(clusters, rejected_answers)
    worker_confidences = make_worker_confidence_map(worker_outputs)
    cluster_scores = [
        score_cluster(cluster, worker_confidences, shared_context)
        for cluster in clusters
    ]

    if not clusters:
        return {
            "selected_cluster_id": None,
            "original_selected_answer": None,
            "selected_answer": None,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "invalid_selected_answer": True,
            "correct": False,
            "strict_equivalence": {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": USE_STRICT_EQUIV,
            },
            "parsed": None,
            "raw_output": "",
            "cluster_scores": [],
            "selected_cluster_score": None,
            "selector_mode": SELECTOR_MODE,
            "verifier_evaluations": [],
            "selected_verifier_score": None,
            "selected_verifier_verdict": None,
            "all_verifier_rejected": False,
            "verified_support_count": 0,
            "verified_block_count": 0,
            "supporting_note_ids": [],
            "blocking_note_ids": [],
            "membership_values_verified": [],
            "completeness_evidence_present": False,
            "missing_verified_members": [],
            "extra_unverified_members": [],
            "set_support_type": "none",
            "final_selection_score": None,
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": None,
                "raw_output_tail": "",
            },
            "finish_reason": "no_valid_non_rejected_clusters",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": 0.0,
            "reason": "all candidate clusters were invalid or already rejected",
        }

    if SELECTOR_MODE == "deterministic":
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
        selected_cluster_score = sorted(cluster_scores, key=final_selector_sort_key)[0]
        selected_cluster = get_cluster_by_id(clusters, to_int(selected_cluster_score.get("cluster_id"), None))
        if selected_cluster is None:
            selected_cluster = clusters[0]
        selected_cluster_id = selected_cluster.get("cluster_id")
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

        print(f"--- DELM deterministic selector, round {round_id}/{MAX_ROUNDS} ---")
        print("selector answer:", short_text(selected_answer, 120))
        print("selector correct:", correct)

        return {
            "selected_cluster_id": selected_cluster_id,
            "original_selected_answer": selected_answer,
            "selected_answer": selected_answer,
            "invalid_selected_answer": False,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "correct": correct,
            "strict_equivalence": verification,
            "parsed": None,
            "raw_output": "",
            "cluster_scores": cluster_scores,
            "selected_cluster_score": selected_cluster_score,
            "selector_mode": "deterministic",
            "verifier_evaluations": [],
            "selected_verifier_score": None,
            "selected_verifier_verdict": None,
            "all_verifier_rejected": False,
            "verified_support_count": selected_cluster_score.get("verified_support_count", 0),
            "verified_block_count": selected_cluster_score.get("verified_block_count", 0),
            "supporting_note_ids": selected_cluster_score.get("supporting_note_ids", []),
            "blocking_note_ids": selected_cluster_score.get("blocking_note_ids", []),
            "membership_values_verified": selected_cluster_score.get("membership_values_verified", []),
            "completeness_evidence_present": selected_cluster_score.get("completeness_evidence_present", False),
            "missing_verified_members": selected_cluster_score.get("missing_verified_members", []),
            "extra_unverified_members": selected_cluster_score.get("extra_unverified_members", []),
            "set_support_type": selected_cluster_score.get("set_support_type", "none"),
            "final_selection_score": selected_cluster_score.get("final_selection_score"),
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": selected_answer,
                "raw_output_tail": "",
            },
            "finish_reason": "deterministic_selector",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": 0.0,
            "reason": "deterministic_selector: selected by support_count, avg_confidence, max_confidence",
        }

    if SELECTOR_MODE in {"verifier", "hybrid"}:
        selected_cluster, selected_evaluation, verifier_evaluations, all_verifier_rejected = (
            select_cluster_with_verifier(
                client=client,
                case=case,
                shared_context=shared_context,
                worker_outputs=worker_outputs,
                clusters=clusters,
                cluster_scores=cluster_scores,
                rejected_answers=rejected_answers,
            )
        )
        selected_cluster_id = selected_cluster.get("cluster_id")
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
        selected_cluster_score = with_final_selection_score(
            score_cluster(selected_cluster, worker_confidences, shared_context),
            selected_evaluation,
        )
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores, verifier_evaluations)
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

        print(f"--- DELM {SELECTOR_MODE} selector, round {round_id}/{MAX_ROUNDS} ---")
        print("selector answer:", short_text(selected_answer, 120))
        print("selector correct:", correct)
        print("selector verifier score:", selected_evaluation.get("score"))
        print("selector verifier verdict:", selected_evaluation.get("verdict"))

        return {
            "selected_cluster_id": selected_cluster_id,
            "original_selected_answer": selected_answer,
            "selected_answer": selected_answer,
            "invalid_selected_answer": False,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "correct": correct,
            "strict_equivalence": verification,
            "parsed": None,
            "raw_output": "",
            "cluster_scores": cluster_scores,
            "selected_cluster_score": selected_cluster_score,
            "selector_mode": SELECTOR_MODE,
            "verifier_evaluations": verifier_evaluations,
            "selected_verifier_score": selected_evaluation.get("score"),
            "selected_verifier_verdict": selected_evaluation.get("verdict"),
            "all_verifier_rejected": all_verifier_rejected,
            "verified_support_count": selected_cluster_score.get("verified_support_count", 0),
            "verified_block_count": selected_cluster_score.get("verified_block_count", 0),
            "supporting_note_ids": selected_cluster_score.get("supporting_note_ids", []),
            "blocking_note_ids": selected_cluster_score.get("blocking_note_ids", []),
            "membership_values_verified": selected_cluster_score.get("membership_values_verified", []),
            "completeness_evidence_present": selected_cluster_score.get("completeness_evidence_present", False),
            "missing_verified_members": selected_cluster_score.get("missing_verified_members", []),
            "extra_unverified_members": selected_cluster_score.get("extra_unverified_members", []),
            "set_support_type": selected_cluster_score.get("set_support_type", "none"),
            "final_selection_score": selected_cluster_score.get("final_selection_score"),
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": selected_answer,
                "raw_output_tail": "",
            },
            "finish_reason": f"{SELECTOR_MODE}_selector",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": sum(
                to_float(evaluation.get("wall_time_seconds"), 0.0)
                for evaluation in verifier_evaluations
            ),
            "reason": (
                f"{SELECTOR_MODE}_selector: selected by verifier score"
                " with deterministic tie-break"
            ),
        }

    print(f"--- DELM selector, round {round_id}/{MAX_ROUNDS} ---")

    prompt = build_delm_selector_prompt(
        case=case,
        round_id=round_id,
        shared_context=shared_context,
        worker_outputs=worker_outputs,
        clusters=clusters,
    )

    result = call_llm(client, prompt, temperature=SELECTOR_TEMPERATURE)

    if result.get("error") is not None or result.get("finish_reason") == "api_error":
        append_jsonl(ERROR_PATH, {
            "id": case.get("id"),
            "method": "delm_lite",
            "round": round_id,
            "stage": "selector",
            "result": result,
        })
        print("[SKIP] DELM selector API error.")
        return None

    parsed = extract_json_object(result.get("content"))
    selected_cluster_id = parse_selected_cluster_id(parsed, result.get("content"))
    selected_answer = parse_answer_from_output(result.get("content"), parsed)
    parser_selected_answer = selected_answer

    selected_cluster = get_cluster_by_id(clusters, selected_cluster_id)
    if selected_cluster is not None:
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))

    selected_cluster_score = None
    if selected_cluster is not None:
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
        selected_cluster_score = with_final_selection_score(
            score_cluster(selected_cluster, worker_confidences, shared_context)
        )

    original_selected_answer = selected_answer
    invalid_selected_answer = not is_valid_answer(selected_answer)
    selector_selected_rejected_answer = (
        False if invalid_selected_answer else answer_in_list(selected_answer, rejected_answers)
    )
    fallback_selected_non_rejected = False
    reason = (parsed or {}).get("reason") if isinstance(parsed, dict) else None
    finish_reason = result.get("finish_reason")

    if invalid_selected_answer or selector_selected_rejected_answer:
        fallback_cluster = clusters[0] if clusters else None
        if fallback_cluster is not None:
            selected_cluster = fallback_cluster
            selected_cluster_id = fallback_cluster.get("cluster_id")
            selected_answer = normalize_answer(fallback_cluster.get("canonical_answer"))
            fallback_selected_non_rejected = True
            if invalid_selected_answer:
                reason = "selector selected an invalid answer; fell back to first non-rejected cluster"
            else:
                reason = "selector selected a rejected answer; fell back to first non-rejected cluster"
        else:
            selected_cluster = None
            selected_cluster_id = None
            selected_answer = None
            finish_reason = "no_valid_non_rejected_clusters"
            reason = "all candidate clusters were invalid or already rejected"

    cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
    selected_cluster_score = (
        with_final_selection_score(score_cluster(selected_cluster, worker_confidences, shared_context))
        if selected_cluster is not None else None
    )
    if selected_answer is None:
        correct = False
        verification = {
            "strict_equiv_result": None,
            "original_equiv_result": False,
            "final_equiv_result": False,
            "use_strict_equiv": USE_STRICT_EQUIV,
        }
    else:
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

    print("selector answer:", short_text(selected_answer, 120))
    print("selector correct:", correct)
    print("selector invalid answer:", invalid_selected_answer)
    print("selector selected rejected answer:", selector_selected_rejected_answer)
    print("selector fallback non-rejected:", fallback_selected_non_rejected)

    return {
        "selected_cluster_id": selected_cluster_id,
        "original_selected_answer": original_selected_answer,
        "selected_answer": selected_answer,
        "invalid_selected_answer": invalid_selected_answer,
        "selector_selected_rejected_answer": selector_selected_rejected_answer,
        "fallback_selected_non_rejected": fallback_selected_non_rejected,
        "correct": correct,
        "strict_equivalence": verification,
        "parsed": parsed,
        "raw_output": result.get("content", ""),
        "cluster_scores": cluster_scores,
        "selected_cluster_score": selected_cluster_score,
        "selector_mode": "llm",
        "verifier_evaluations": [],
        "selected_verifier_score": None,
        "selected_verifier_verdict": None,
        "all_verifier_rejected": False,
        "verified_support_count": (selected_cluster_score or {}).get("verified_support_count", 0),
        "verified_block_count": (selected_cluster_score or {}).get("verified_block_count", 0),
        "supporting_note_ids": (selected_cluster_score or {}).get("supporting_note_ids", []),
        "blocking_note_ids": (selected_cluster_score or {}).get("blocking_note_ids", []),
        "membership_values_verified": (selected_cluster_score or {}).get("membership_values_verified", []),
        "completeness_evidence_present": (selected_cluster_score or {}).get("completeness_evidence_present", False),
        "missing_verified_members": (selected_cluster_score or {}).get("missing_verified_members", []),
        "extra_unverified_members": (selected_cluster_score or {}).get("extra_unverified_members", []),
        "set_support_type": (selected_cluster_score or {}).get("set_support_type", "none"),
        "final_selection_score": (selected_cluster_score or {}).get("final_selection_score"),
        "parser_debug": {
            "parsed_json": parsed is not None,
            "parsed_keys": list(parsed.keys()) if parsed else [],
            "extracted_answer": parser_selected_answer,
            "raw_output_tail": tail_text(result.get("content", ""), 500),
        },
        "finish_reason": finish_reason,
        "usage": result.get("usage"),
        "api_call": True,
        "wall_time_seconds": result.get("wall_time_seconds"),
        "reason": reason,
    }


def update_shared_context_after_round(
    shared_context: dict[str, Any],
    round_record: dict[str, Any],
) -> dict[str, Any]:
    submitted_answer = normalize_answer(round_record.get("submitted_answer"))
    selector = round_record.get("selector") or {}
    selector_parsed = selector.get("parsed") or {}
    feedback = "incorrect" if is_valid_answer(submitted_answer) else "invalid_or_no_submission"

    if is_valid_answer(submitted_answer):
        shared_context.setdefault("rejected_answers", []).append({
            "round": round_record.get("round"),
            "answer": submitted_answer,
            "oracle_feedback": "incorrect",
        })

    reason = selector_parsed.get("reason") or selector.get("reason")
    if reason:
        shared_context.setdefault("failed_attempt_summaries", []).append({
            "round": round_record.get("round"),
            "submitted_answer": submitted_answer,
            "summary": short_text(reason, 500),
        })

    diagnostic = selector.get("diagnostic")
    if isinstance(diagnostic, dict):
        shared_context.setdefault("diagnostics", []).append({
            "round": round_record.get("round"),
            "submitted_answer": submitted_answer,
            "diagnosis": diagnostic.get("diagnosis"),
            "likely_error_type": diagnostic.get("likely_error_type"),
            "banned_assumption": diagnostic.get("banned_assumption"),
            "must_check": diagnostic.get("must_check"),
            "next_strategy_hint": diagnostic.get("next_strategy_hint"),
        })

        banned_assumption = str(diagnostic.get("banned_assumption") or "").strip()
        if banned_assumption:
            shared_context.setdefault("banned_assumptions", []).append(banned_assumption)

        for item in diagnostic.get("must_check") or []:
            item = str(item or "").strip()
            if item:
                shared_context.setdefault("must_check_items", []).append(item)

        strategy_hint = str(diagnostic.get("next_strategy_hint") or "").strip()
        if strategy_hint:
            shared_context.setdefault("strategy_hints", []).append(strategy_hint)

    worker_summaries = []
    for worker in round_record.get("workers", []):
        parsed = worker.get("parsed") or {}
        worker_summaries.append({
            "worker_id": worker.get("worker_id"),
            "answer": worker.get("answer"),
            "strategy": parsed.get("strategy"),
            "reason": short_text(parsed.get("reason"), 300),
        })

    shared_context.setdefault("round_notes", []).append({
        "round": round_record.get("round"),
        "submitted_answer": submitted_answer,
        "feedback": feedback,
        "worker_candidate_summaries": worker_summaries,
    })

    return shared_context


def run_delm_lite_feedback_retry(client, case: dict[str, Any]) -> dict[str, Any] | None:
    if USE_RAW_INIT and case_raw_correct(case) is True:
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

    if USE_RAW_INIT and case_raw_correct(case) is False:
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

    for round_id in range(1, MAX_ROUNDS + 1):
        print(f"--- DELM-lite round {round_id}/{MAX_ROUNDS} ---")

        context_before = json.loads(json.dumps(shared_context, ensure_ascii=False))

        worker_outputs = run_delm_workers(client, case, round_id, shared_context)
        if worker_outputs is None:
            return None

        if TRACK_LATENT_WORKER_SOLVE and any(w.get("correct") is True for w in worker_outputs):
            latent_worker_solved = True

        note_admission = {
            "verified_notes": [],
            "rejected_notes": [],
            "admission_results": [],
            "admission_evaluations": 0,
            "admission_calls": 0,
            "admission_tokens": 0,
        }
        if USE_VERIFIED_NOTES:
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

        if USE_DIAGNOSTIC and correct is not True and is_valid_answer(submitted_answer):
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

        time.sleep(SLEEP_SECONDS)

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
        to_int((round_record.get("note_admission") or {}).get("admission_evaluations"), 0) or 0
        for round_record in rounds
    )
    admission_calls = sum(
        to_int((round_record.get("note_admission") or {}).get("admission_calls"), 0) or 0
        for round_record in rounds
    )
    admission_tokens = sum(
        to_int((round_record.get("note_admission") or {}).get("admission_tokens"), 0) or 0
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

        if to_int(selector.get("verified_support_count"), 0):
            verified_support_selected_count += 1

        for cluster_score in selector.get("cluster_scores", []) or []:
            if to_int(cluster_score.get("verified_block_count"), 0):
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


def run_case(client, case: dict[str, Any]) -> dict[str, Any] | None:
    identity = get_case_identity(case)

    record = {
        **identity,
        "benchmark": "oracle-feedback iterative repair",
        "settings": {
            "max_rounds": MAX_ROUNDS,
            "delm_workers": DELM_WORKERS,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "selector_temperature": SELECTOR_TEMPERATURE,
            "use_llm_selector": USE_LLM_SELECTOR,
            "only_low_conf": ONLY_LOW_CONF,
            "low_conf_max_support": LOW_CONF_MAX_SUPPORT,
            "only_raw_wrong": ONLY_RAW_WRONG,
            "use_raw_init": USE_RAW_INIT,
            "use_diagnostic": USE_DIAGNOSTIC,
            "diag_max_tokens": DIAG_MAX_TOKENS,
            "diag_temperature": DIAG_TEMPERATURE,
            "use_verified_notes": USE_VERIFIED_NOTES,
            "use_strict_equiv": USE_STRICT_EQUIV,
            "use_task_queue": USE_TASK_QUEUE,
            "task_queue_mode": TASK_QUEUE_MODE,
            "admission_max_tokens": ADMISSION_MAX_TOKENS,
            "admission_temperature": ADMISSION_TEMPERATURE,
            "use_llm_admission": USE_LLM_ADMISSION,
            "selector_mode": SELECTOR_MODE,
            "verifier_max_tokens": VERIFIER_MAX_TOKENS,
            "verifier_temperature": VERIFIER_TEMPERATURE,
        },
        "main_agent": None,
        "delm_lite": None,
    }

    if RUN_MAIN_AGENT:
        print("\n### Running Main-Agent Feedback Retry ###")
        main_result = run_main_agent_feedback_retry(client, case)
        if main_result is None:
            return None
        record["main_agent"] = main_result

    if RUN_DELM_LITE:
        print("\n### Running DELM-lite Feedback Retry ###")
        delm_result = run_delm_lite_feedback_retry(client, case)
        if delm_result is None:
            return None
        record["delm_lite"] = delm_result

    return record


def method_result(record: dict[str, Any], method_key: str) -> dict[str, Any]:
    value = record.get(method_key)

    if isinstance(value, dict):
        return value

    return {
        "solved": False,
        "rounds_used": 0,
        "api_calls": 0,
        "usage": {},
        "wall_time_seconds": 0.0,
        "wrong_submitted_answers": [],
        "repeated_wrong_answer_count": 0,
        "duplicate_forbidden_answer_count": 0,
        "invalid_answer_count": 0,
        "truncated_answer_count": 0,
        "parser_invalid_count": 0,
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
    }


def summarize_method(records: list[dict[str, Any]], method_key: str) -> dict[str, Any]:
    total = len(records)
    solved = 0
    total_rounds = 0
    total_rounds_solved_only = 0
    total_api_calls = 0
    total_tokens = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_wall = 0.0
    total_repeated_wrong = 0
    total_duplicate_forbidden = 0
    total_invalid_answers = 0
    total_truncated_answers = 0
    total_parser_invalid = 0
    total_diagnostic_calls = 0
    total_diagnostic_tokens = 0
    total_verifier_calls = 0
    total_verifier_tokens = 0
    total_verified_notes_added = 0
    total_rejected_notes = 0
    total_uncertain_notes = 0
    total_admission_evaluations = 0
    total_admission_calls = 0
    total_admission_tokens = 0
    total_strict_false_positives_prevented = 0
    total_verified_support_selected = 0
    total_verified_blocked_candidates = 0
    latent_worker_solved = 0

    solved_ids = []

    for record in records:
        result = method_result(record, method_key)

        is_solved = result.get("solved") is True
        solved += int(is_solved)

        if is_solved:
            solved_ids.append(record.get("id"))
            total_rounds_solved_only += to_int(result.get("rounds_used"), 0) or 0

        total_rounds += to_int(result.get("rounds_used"), 0) or 0
        total_api_calls += to_int(result.get("api_calls"), 0) or 0

        usage = result.get("usage") or {}
        total_tokens += usage_total_tokens(usage)
        total_prompt_tokens += usage_prompt_tokens(usage)
        total_completion_tokens += usage_completion_tokens(usage)

        total_wall += to_float(result.get("wall_time_seconds"), 0.0)
        total_repeated_wrong += to_int(result.get("repeated_wrong_answer_count"), 0) or 0
        total_diagnostic_calls += to_int(result.get("diagnostic_calls"), 0) or 0
        total_diagnostic_tokens += to_int(result.get("diagnostic_tokens"), 0) or 0
        total_verifier_calls += to_int(result.get("verifier_calls"), 0) or 0
        total_verifier_tokens += to_int(result.get("verifier_tokens"), 0) or 0
        total_verified_notes_added += to_int(result.get("verified_notes_added"), 0) or 0
        total_rejected_notes += to_int(result.get("rejected_notes_count"), 0) or 0
        total_uncertain_notes += to_int(result.get("uncertain_notes_count"), 0) or 0
        total_admission_evaluations += to_int(result.get("admission_evaluations"), 0) or 0
        total_admission_calls += to_int(result.get("admission_calls"), 0) or 0
        total_admission_tokens += to_int(result.get("admission_tokens"), 0) or 0
        total_strict_false_positives_prevented += (
            to_int(result.get("strict_equiv_false_positives_prevented"), 0) or 0
        )
        total_verified_support_selected += to_int(result.get("verified_support_selected_count"), 0) or 0
        total_verified_blocked_candidates += to_int(result.get("verified_blocked_candidate_count"), 0) or 0
        duplicate_forbidden_count = to_int(result.get("duplicate_forbidden_answer_count"), None)
        invalid_answer_count = to_int(result.get("invalid_answer_count"), None)
        truncated_answer_count = to_int(result.get("truncated_answer_count"), None)
        parser_invalid_count = to_int(result.get("parser_invalid_count"), None)

        if duplicate_forbidden_count is None:
            if method_key == "main_agent":
                duplicate_forbidden_count = sum(
                    1 for attempt in result.get("attempts", [])
                    if attempt.get("duplicate_forbidden_answer") is True
                )
            elif method_key == "delm_lite":
                duplicate_forbidden_count = sum(
                    1 for round_record in result.get("rounds", [])
                    if (round_record.get("selector") or {}).get("selector_selected_rejected_answer") is True
                )
            else:
                duplicate_forbidden_count = 0

        total_duplicate_forbidden += duplicate_forbidden_count

        if invalid_answer_count is None:
            if method_key == "main_agent":
                invalid_answer_count = invalid_metric_counts(
                    result.get("attempts", []),
                    "invalid_answer",
                )["invalid_answer_count"]
            elif method_key == "delm_lite":
                invalid_answer_count = 0
                for round_record in result.get("rounds", []):
                    invalid_answer_count += invalid_metric_counts(
                        round_record.get("workers", []),
                        "invalid_answer",
                    )["invalid_answer_count"]
                    invalid_answer_count += invalid_metric_counts(
                        [round_record.get("selector") or {}],
                        "invalid_selected_answer",
                    )["invalid_answer_count"]
            else:
                invalid_answer_count = 0

        if truncated_answer_count is None:
            if method_key == "main_agent":
                truncated_answer_count = invalid_metric_counts(
                    result.get("attempts", []),
                    "invalid_answer",
                )["truncated_answer_count"]
            elif method_key == "delm_lite":
                truncated_answer_count = 0
                for round_record in result.get("rounds", []):
                    truncated_answer_count += invalid_metric_counts(
                        round_record.get("workers", []),
                        "invalid_answer",
                    )["truncated_answer_count"]
                    truncated_answer_count += invalid_metric_counts(
                        [round_record.get("selector") or {}],
                        "invalid_selected_answer",
                    )["truncated_answer_count"]
            else:
                truncated_answer_count = 0

        if parser_invalid_count is None:
            if method_key == "main_agent":
                parser_invalid_count = invalid_metric_counts(
                    result.get("attempts", []),
                    "invalid_answer",
                )["parser_invalid_count"]
            elif method_key == "delm_lite":
                parser_invalid_count = 0
                for round_record in result.get("rounds", []):
                    parser_invalid_count += invalid_metric_counts(
                        round_record.get("workers", []),
                        "invalid_answer",
                    )["parser_invalid_count"]
                    parser_invalid_count += invalid_metric_counts(
                        [round_record.get("selector") or {}],
                        "invalid_selected_answer",
                    )["parser_invalid_count"]
            else:
                parser_invalid_count = 0

        total_invalid_answers += invalid_answer_count
        total_truncated_answers += truncated_answer_count
        total_parser_invalid += parser_invalid_count

        if result.get("latent_worker_solved") is True:
            latent_worker_solved += 1

    return {
        "total": total,
        "solved": solved,
        "solved_ids": solved_ids,
        "solved_rate": pct(solved, total),
        "avg_rounds_all": f"{total_rounds / total:.2f}" if total else "N/A",
        "avg_rounds_to_solve": f"{total_rounds_solved_only / solved:.2f}" if solved else "N/A",
        "api_calls": total_api_calls,
        "api_calls_per_solved": f"{total_api_calls / solved:.2f}" if solved else "N/A",
        "total_tokens": total_tokens,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "tokens_per_solved": f"{total_tokens / solved:.2f}" if solved else "N/A",
        "wall_time_seconds": total_wall,
        "wall_time_per_solved": f"{total_wall / solved:.2f}" if solved else "N/A",
        "solved_per_minute": f"{solved / total_wall * 60:.4f}" if total_wall > 0 else "N/A",
        "repeated_wrong_answer_count": total_repeated_wrong,
        "duplicate_forbidden_answer_count": total_duplicate_forbidden,
        "invalid_answer_count": total_invalid_answers,
        "truncated_answer_count": total_truncated_answers,
        "parser_invalid_count": total_parser_invalid,
        "diagnostic_calls": total_diagnostic_calls,
        "diagnostic_tokens": total_diagnostic_tokens,
        "verifier_calls": total_verifier_calls,
        "verifier_tokens": total_verifier_tokens,
        "verified_notes_added": total_verified_notes_added,
        "rejected_notes_count": total_rejected_notes,
        "uncertain_notes_count": total_uncertain_notes,
        "admission_evaluations": total_admission_evaluations,
        "admission_calls": total_admission_calls,
        "admission_tokens": total_admission_tokens,
        "strict_equiv_false_positives_prevented": total_strict_false_positives_prevented,
        "verified_support_selected_count": total_verified_support_selected,
        "verified_blocked_candidate_count": total_verified_blocked_candidates,
        "latent_worker_solved": latent_worker_solved,
    }


def summarize_by_answer_type(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        answer_type = str(record.get("answer_type") or "unknown")
        grouped[answer_type].append(record)

    out = {}

    for answer_type, group_records in sorted(grouped.items()):
        out[answer_type] = {
            "total": len(group_records),
            "main_agent": summarize_method(group_records, "main_agent"),
            "delm_lite": summarize_method(group_records, "delm_lite"),
        }

    return out


def make_summary_json(records: list[dict[str, Any]]) -> dict[str, Any]:
    main_summary = summarize_method(records, "main_agent")
    delm_summary = summarize_method(records, "delm_lite")
    settings = {
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "selector_temperature": SELECTOR_TEMPERATURE,
        "use_llm_selector": USE_LLM_SELECTOR,
        "selector_mode": SELECTOR_MODE,
        "verifier_max_tokens": VERIFIER_MAX_TOKENS,
        "verifier_temperature": VERIFIER_TEMPERATURE,
        "max_rounds": MAX_ROUNDS,
        "delm_workers": DELM_WORKERS,
        "only_low_conf": ONLY_LOW_CONF,
        "low_conf_max_support": LOW_CONF_MAX_SUPPORT,
        "only_raw_wrong": ONLY_RAW_WRONG,
        "use_raw_init": USE_RAW_INIT,
        "use_diagnostic": USE_DIAGNOSTIC,
        "diag_max_tokens": DIAG_MAX_TOKENS,
        "diag_temperature": DIAG_TEMPERATURE,
        "use_verified_notes": USE_VERIFIED_NOTES,
        "use_strict_equiv": USE_STRICT_EQUIV,
        "use_task_queue": USE_TASK_QUEUE,
        "task_queue_mode": TASK_QUEUE_MODE,
        "admission_max_tokens": ADMISSION_MAX_TOKENS,
        "admission_temperature": ADMISSION_TEMPERATURE,
        "use_llm_admission": USE_LLM_ADMISSION,
        "run_main_agent": RUN_MAIN_AGENT,
        "run_delm_lite": RUN_DELM_LITE,
    }

    return {
        "input": str(INPUT_PATH),
        "output": str(OUT_PATH),
        "environment": settings,
        "settings": settings,
        "summary": {
            "total": len(records),
            "main_agent": main_summary,
            "delm_lite": delm_summary,
            "delm_minus_main_solved": delm_summary["solved"] - main_summary["solved"],
            "by_answer_type": summarize_by_answer_type(records),
        },
    }


def make_md_report(records: list[dict[str, Any]]) -> str:
    records = sorted(records, key=lambda r: int(r["id"]))
    summary = make_summary_json(records)["summary"]

    main = summary["main_agent"]
    delm = summary["delm_lite"]

    lines = []

    lines.append("# Oracle-feedback Iterative Repair Benchmark")
    lines.append("")
    lines.append(f"- Input: `{INPUT_PATH}`")
    lines.append(f"- Output: `{OUT_PATH}`")
    lines.append(f"- Only low-confidence cases: `{ONLY_LOW_CONF}`")
    lines.append(f"- Low-confidence rule: `raw_selected_support <= {LOW_CONF_MAX_SUPPORT}`")
    lines.append(f"- Only raw-wrong cases: `{ONLY_RAW_WRONG}`")
    lines.append(f"- Use raw vote initialization: `{USE_RAW_INIT}`")
    lines.append(f"- Use diagnostic feedback: `{USE_DIAGNOSTIC}`")
    lines.append(f"- Diagnostic max tokens: `{DIAG_MAX_TOKENS}`")
    lines.append(f"- Diagnostic temperature: `{DIAG_TEMPERATURE}`")
    lines.append(f"- Use verified notes: `{USE_VERIFIED_NOTES}`")
    lines.append(f"- Use strict equivalence guard: `{USE_STRICT_EQUIV}`")
    lines.append(f"- Use task queue roles: `{USE_TASK_QUEUE}`")
    lines.append(f"- Task queue mode: `{TASK_QUEUE_MODE}`")
    lines.append(f"- Admission max tokens: `{ADMISSION_MAX_TOKENS}`")
    lines.append(f"- Admission temperature: `{ADMISSION_TEMPERATURE}`")
    lines.append(f"- Use LLM admission fallback: `{USE_LLM_ADMISSION}`")
    lines.append(f"- Max rounds per problem: `{MAX_ROUNDS}`")
    lines.append(f"- DELM workers per round: `{DELM_WORKERS}`")
    lines.append(f"- Max tokens per call: `{MAX_TOKENS}`")
    lines.append(f"- Worker/Main temperature: `{TEMPERATURE}`")
    lines.append(f"- Selector temperature: `{SELECTOR_TEMPERATURE}`")
    lines.append(f"- Use LLM selector: `{USE_LLM_SELECTOR}`")
    lines.append(f"- Selector mode: `{SELECTOR_MODE}`")
    lines.append(f"- Verifier max tokens: `{VERIFIER_MAX_TOKENS}`")
    lines.append(f"- Verifier temperature: `{VERIFIER_TEMPERATURE}`")
    lines.append("")
    lines.append("Oracle feedback only tells the model whether its submitted answer is incorrect. The gold answer is never shown in prompts.")
    lines.append("")

    lines.append("## Main Result")
    lines.append("")
    lines.append(md_table(
        [
            "Method",
            "Solved",
            "Total",
            "Solved rate",
            "Avg rounds to solve",
            "API calls",
            "Tokens / solved",
            "Wall-time / solved",
            "Solved / minute",
            "Repeated wrong answers",
            "Duplicate forbidden answers",
            "Invalid answers",
            "Truncated answers",
            "Parser-invalid answers",
            "Diagnostic calls",
            "Diagnostic tokens",
            "Verifier calls",
            "Verifier tokens",
            "Admission calls",
            "Admission evaluations",
            "Admission tokens",
            "Verified notes",
            "Rejected notes",
            "Uncertain notes",
        ],
        [
            [
                "Main-Agent Feedback Retry",
                main["solved"],
                main["total"],
                main["solved_rate"],
                main["avg_rounds_to_solve"],
                main["api_calls"],
                main["tokens_per_solved"],
                main["wall_time_per_solved"],
                main["solved_per_minute"],
                main["repeated_wrong_answer_count"],
                main["duplicate_forbidden_answer_count"],
                main["invalid_answer_count"],
                main["truncated_answer_count"],
                main["parser_invalid_count"],
                main["diagnostic_calls"],
                main["diagnostic_tokens"],
                main["verifier_calls"],
                main["verifier_tokens"],
                main["admission_calls"],
                main["admission_evaluations"],
                main["admission_tokens"],
                main["verified_notes_added"],
                main["rejected_notes_count"],
                main["uncertain_notes_count"],
            ],
            [
                "DELM-lite Feedback Retry",
                delm["solved"],
                delm["total"],
                delm["solved_rate"],
                delm["avg_rounds_to_solve"],
                delm["api_calls"],
                delm["tokens_per_solved"],
                delm["wall_time_per_solved"],
                delm["solved_per_minute"],
                delm["repeated_wrong_answer_count"],
                delm["duplicate_forbidden_answer_count"],
                delm["invalid_answer_count"],
                delm["truncated_answer_count"],
                delm["parser_invalid_count"],
                delm["diagnostic_calls"],
                delm["diagnostic_tokens"],
                delm["verifier_calls"],
                delm["verifier_tokens"],
                delm["admission_calls"],
                delm["admission_evaluations"],
                delm["admission_tokens"],
                delm["verified_notes_added"],
                delm["rejected_notes_count"],
                delm["uncertain_notes_count"],
            ],
        ],
    ))
    lines.append("")
    lines.append(f"- DELM minus Main-Agent solved count: **{summary['delm_minus_main_solved']}**")
    lines.append(f"- DELM latent worker solved count: **{delm.get('latent_worker_solved')}**")
    lines.append(f"- DELM verified support selected count: **{delm.get('verified_support_selected_count')}**")
    lines.append(f"- DELM verified blocked candidate count: **{delm.get('verified_blocked_candidate_count')}**")
    lines.append(f"- DELM strict equivalence false positives prevented: **{delm.get('strict_equiv_false_positives_prevented')}**")
    lines.append("")

    lines.append("## Accuracy by Answer Type")
    lines.append("")
    type_rows = []

    for answer_type, stats in summary["by_answer_type"].items():
        m = stats["main_agent"]
        d = stats["delm_lite"]
        type_rows.append([
            answer_type,
            stats["total"],
            m["solved"],
            d["solved"],
            m["solved_rate"],
            d["solved_rate"],
            d["solved"] - m["solved"],
        ])

    lines.append(md_table(
        [
            "answer_type",
            "total",
            "main_solved",
            "delm_solved",
            "main_rate",
            "delm_rate",
            "delm-main",
        ],
        type_rows,
    ))
    lines.append("")

    lines.append("## Case Table")
    lines.append("")
    case_rows = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        case_rows.append([
            record.get("id"),
            record.get("question_id"),
            record.get("answer_type"),
            record.get("raw_selected_support"),
            short_text(record.get("gold"), 80),
            main_result.get("solved"),
            short_text(main_result.get("final_answer"), 80),
            main_result.get("rounds_used"),
            delm_result.get("solved"),
            short_text(delm_result.get("final_answer"), 80),
            delm_result.get("rounds_used"),
            delm_result.get("latent_worker_solved"),
        ])

    lines.append(md_table(
        [
            "id",
            "qid",
            "type",
            "support",
            "gold",
            "main_solved",
            "main_final",
            "main_rounds",
            "delm_solved",
            "delm_final",
            "delm_rounds",
            "delm_latent",
        ],
        case_rows,
    ))
    lines.append("")

    lines.append("## Cases Solved by DELM but not Main-Agent")
    lines.append("")
    delm_only = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        if delm_result.get("solved") is True and main_result.get("solved") is not True:
            delm_only.append(record)

    if not delm_only:
        lines.append("No case was solved by DELM-lite only.")
        lines.append("")
    else:
        for record in delm_only:
            main_result = method_result(record, "main_agent")
            delm_result = method_result(record, "delm_lite")

            lines.append(f"### Case id={record.get('id')}, question_id={record.get('question_id')}")
            lines.append("")
            lines.append(f"- Gold: `{short_text(record.get('gold'), 200)}`")
            lines.append(f"- Main final: `{short_text(main_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM final: `{short_text(delm_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM rounds used: `{delm_result.get('rounds_used')}`")
            lines.append("")

    lines.append("## Cases Solved by Main-Agent but not DELM")
    lines.append("")
    main_only = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        if main_result.get("solved") is True and delm_result.get("solved") is not True:
            main_only.append(record)

    if not main_only:
        lines.append("No case was solved by Main-Agent only.")
        lines.append("")
    else:
        for record in main_only:
            main_result = method_result(record, "main_agent")
            delm_result = method_result(record, "delm_lite")

            lines.append(f"### Case id={record.get('id')}, question_id={record.get('question_id')}")
            lines.append("")
            lines.append(f"- Gold: `{short_text(record.get('gold'), 200)}`")
            lines.append(f"- Main final: `{short_text(main_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM final: `{short_text(delm_result.get('final_answer'), 200)}`")
            lines.append(f"- Main rounds used: `{main_result.get('rounds_used')}`")
            lines.append("")

    return "\n".join(lines)


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Missing {INPUT_PATH}\n"
            "Please run `python scripts/analyze_sc3_amo_parser.py` first."
        )

    cases = read_jsonl(INPUT_PATH)
    cases.sort(key=lambda r: int(r["id"]))

    requested_case_ids = parse_case_ids_from_env()

    if requested_case_ids is not None:
        cases = [
            case for case in cases
            if to_int(case.get("id"), None) in requested_case_ids
        ]
    else:
        cases = [case for case in cases if should_include_case(case)]

        if ONLY_RAW_WRONG:
            cases = [
                case for case in cases
                if case_raw_correct(case) is False
            ]

        if LIMIT > 0:
            cases = cases[:LIMIT]

    if requested_case_ids is not None and ONLY_RAW_WRONG:
        cases = [
            case for case in cases
            if case_raw_correct(case) is False
        ]

    done_ids = load_done_ids(OUT_PATH)

    print("Input:", INPUT_PATH)
    print("Output:", OUT_PATH)
    print("Error log:", ERROR_PATH)
    print("Report:", OUT_MD)
    print("Cases selected:", len(cases))
    print("Already done:", len(done_ids))
    print("Only low confidence:", ONLY_LOW_CONF)
    print("Low confidence max support:", LOW_CONF_MAX_SUPPORT)
    print("Only raw wrong:", ONLY_RAW_WRONG)
    print("Use raw init:", USE_RAW_INIT)
    print("Use diagnostic:", USE_DIAGNOSTIC)
    print("Diagnostic max tokens:", DIAG_MAX_TOKENS)
    print("Diagnostic temperature:", DIAG_TEMPERATURE)
    print("Use verified notes:", USE_VERIFIED_NOTES)
    print("Use strict equivalence:", USE_STRICT_EQUIV)
    print("Use task queue:", USE_TASK_QUEUE)
    print("Task queue mode:", TASK_QUEUE_MODE)
    print("Admission max tokens:", ADMISSION_MAX_TOKENS)
    print("Admission temperature:", ADMISSION_TEMPERATURE)
    print("Use LLM admission fallback:", USE_LLM_ADMISSION)
    print("Case ids filter:", sorted(requested_case_ids) if requested_case_ids is not None else "None")
    print("Max rounds:", MAX_ROUNDS)
    print("DELM workers:", DELM_WORKERS)
    print("Max tokens:", MAX_TOKENS)
    print("Temperature:", TEMPERATURE)
    print("Selector temperature:", SELECTOR_TEMPERATURE)
    print("Use LLM selector:", USE_LLM_SELECTOR)
    print("Selector mode:", SELECTOR_MODE)
    print("Verifier max tokens:", VERIFIER_MAX_TOKENS)
    print("Verifier temperature:", VERIFIER_TEMPERATURE)
    print("Run Main-Agent:", RUN_MAIN_AGENT)
    print("Run DELM-lite:", RUN_DELM_LITE)
    print("Limit:", "ignored by FEEDBACK_CASE_IDS" if requested_case_ids is not None else (LIMIT if LIMIT > 0 else "None"))

    client = get_client()

    for n, case in enumerate(cases, start=1):
        idx = int(case["id"])

        if idx in done_ids:
            continue

        print(
            f"\n===== Feedback Repair Case {n}/{len(cases)}, "
            f"id={idx}, qid={case.get('question_id')}, "
            f"type={case.get('answer_type')}, "
            f"support={case.get('raw_selected_support')} ====="
        )

        record = run_case(client, case)

        if record is None:
            continue

        append_jsonl(OUT_PATH, record)

        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        print("\n--- Case summary ---")
        print("gold:", short_text(record.get("gold"), 120))
        print("main solved:", main_result.get("solved"))
        print("main final:", short_text(main_result.get("final_answer"), 120))
        print("main rounds:", main_result.get("rounds_used"))
        print("delm solved:", delm_result.get("solved"))
        print("delm final:", short_text(delm_result.get("final_answer"), 120))
        print("delm rounds:", delm_result.get("rounds_used"))
        print("delm latent worker solved:", delm_result.get("latent_worker_solved"))

        time.sleep(SLEEP_SECONDS)

    final_records = read_jsonl(OUT_PATH)
    final_records.sort(key=lambda r: int(r["id"]))

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(make_md_report(final_records), encoding="utf-8")

    OUT_SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_SUMMARY_JSON.write_text(
        json.dumps(make_summary_json(final_records), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = make_summary_json(final_records)["summary"]
    main_summary = summary["main_agent"]
    delm_summary = summary["delm_lite"]

    print("\n=== Feedback Repair Benchmark Results ===")
    print("Total completed:", summary["total"])
    print("Main-Agent solved:", main_summary["solved"], main_summary["solved_rate"])
    print("Main-Agent solved per minute:", main_summary["solved_per_minute"])
    print("Main-Agent tokens per solved:", main_summary["tokens_per_solved"])
    print("Main-Agent repeated wrong answers:", main_summary["repeated_wrong_answer_count"])
    print("Main-Agent duplicate forbidden answers:", main_summary["duplicate_forbidden_answer_count"])
    print("Main-Agent invalid answers:", main_summary["invalid_answer_count"])
    print("Main-Agent truncated answers:", main_summary["truncated_answer_count"])
    print("Main-Agent parser-invalid answers:", main_summary["parser_invalid_count"])
    print("Main-Agent diagnostic calls:", main_summary["diagnostic_calls"])
    print("Main-Agent diagnostic tokens:", main_summary["diagnostic_tokens"])
    print("Main-Agent verifier calls:", main_summary["verifier_calls"])
    print("Main-Agent verifier tokens:", main_summary["verifier_tokens"])
    print("DELM-lite solved:", delm_summary["solved"], delm_summary["solved_rate"])
    print("DELM-lite solved per minute:", delm_summary["solved_per_minute"])
    print("DELM-lite tokens per solved:", delm_summary["tokens_per_solved"])
    print("DELM-lite repeated wrong answers:", delm_summary["repeated_wrong_answer_count"])
    print("DELM-lite duplicate forbidden answers:", delm_summary["duplicate_forbidden_answer_count"])
    print("DELM-lite invalid answers:", delm_summary["invalid_answer_count"])
    print("DELM-lite truncated answers:", delm_summary["truncated_answer_count"])
    print("DELM-lite parser-invalid answers:", delm_summary["parser_invalid_count"])
    print("DELM-lite diagnostic calls:", delm_summary["diagnostic_calls"])
    print("DELM-lite diagnostic tokens:", delm_summary["diagnostic_tokens"])
    print("DELM-lite verifier calls:", delm_summary["verifier_calls"])
    print("DELM-lite verifier tokens:", delm_summary["verifier_tokens"])
    print("DELM-lite verified notes added:", delm_summary["verified_notes_added"])
    print("DELM-lite rejected notes:", delm_summary["rejected_notes_count"])
    print("DELM-lite uncertain notes:", delm_summary["uncertain_notes_count"])
    print("DELM-lite admission evaluations:", delm_summary["admission_evaluations"])
    print("DELM-lite admission calls:", delm_summary["admission_calls"])
    print("DELM-lite admission tokens:", delm_summary["admission_tokens"])
    print("DELM-lite strict false positives prevented:", delm_summary["strict_equiv_false_positives_prevented"])
    print("DELM-lite verified support selected:", delm_summary["verified_support_selected_count"])
    print("DELM-lite verified blocked candidates:", delm_summary["verified_blocked_candidate_count"])
    print("DELM minus Main-Agent solved count:", summary["delm_minus_main_solved"])
    print("DELM latent worker solved count:", delm_summary["latent_worker_solved"])

    print("\nSaved:")
    print("-", OUT_PATH)
    print("-", ERROR_PATH)
    print("-", OUT_MD)
    print("-", OUT_SUMMARY_JSON)


if __name__ == "__main__":
    main()
