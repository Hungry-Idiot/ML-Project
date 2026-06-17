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

from src.math_delm.repair.answer_parser import is_parser_invalid_item, is_truncated_answer_item


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


def repeated_wrong_answer_count(wrong_answers: list[str]) -> int:
    counts = Counter(wrong_answers)
    return sum(count - 1 for count in counts.values() if count > 1)


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
            total_rounds_solved_only += cfg.to_int(result.get("rounds_used"), 0) or 0

        total_rounds += cfg.to_int(result.get("rounds_used"), 0) or 0
        total_api_calls += cfg.to_int(result.get("api_calls"), 0) or 0

        usage = result.get("usage") or {}
        total_tokens += usage_total_tokens(usage)
        total_prompt_tokens += usage_prompt_tokens(usage)
        total_completion_tokens += usage_completion_tokens(usage)

        total_wall += cfg.to_float(result.get("wall_time_seconds"), 0.0)
        total_repeated_wrong += cfg.to_int(result.get("repeated_wrong_answer_count"), 0) or 0
        total_diagnostic_calls += cfg.to_int(result.get("diagnostic_calls"), 0) or 0
        total_diagnostic_tokens += cfg.to_int(result.get("diagnostic_tokens"), 0) or 0
        total_verifier_calls += cfg.to_int(result.get("verifier_calls"), 0) or 0
        total_verifier_tokens += cfg.to_int(result.get("verifier_tokens"), 0) or 0
        total_verified_notes_added += cfg.to_int(result.get("verified_notes_added"), 0) or 0
        total_rejected_notes += cfg.to_int(result.get("rejected_notes_count"), 0) or 0
        total_uncertain_notes += cfg.to_int(result.get("uncertain_notes_count"), 0) or 0
        total_admission_evaluations += cfg.to_int(result.get("admission_evaluations"), 0) or 0
        total_admission_calls += cfg.to_int(result.get("admission_calls"), 0) or 0
        total_admission_tokens += cfg.to_int(result.get("admission_tokens"), 0) or 0
        total_strict_false_positives_prevented += (
            cfg.to_int(result.get("strict_equiv_false_positives_prevented"), 0) or 0
        )
        total_verified_support_selected += cfg.to_int(result.get("verified_support_selected_count"), 0) or 0
        total_verified_blocked_candidates += cfg.to_int(result.get("verified_blocked_candidate_count"), 0) or 0
        duplicate_forbidden_count = cfg.to_int(result.get("duplicate_forbidden_answer_count"), None)
        invalid_answer_count = cfg.to_int(result.get("invalid_answer_count"), None)
        truncated_answer_count = cfg.to_int(result.get("truncated_answer_count"), None)
        parser_invalid_count = cfg.to_int(result.get("parser_invalid_count"), None)

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
        "max_tokens": cfg.MAX_TOKENS,
        "temperature": cfg.TEMPERATURE,
        "selector_temperature": cfg.SELECTOR_TEMPERATURE,
        "use_llm_selector": cfg.USE_LLM_SELECTOR,
        "selector_mode": cfg.SELECTOR_MODE,
        "verifier_max_tokens": cfg.VERIFIER_MAX_TOKENS,
        "verifier_temperature": cfg.VERIFIER_TEMPERATURE,
        "max_rounds": cfg.MAX_ROUNDS,
        "delm_workers": cfg.DELM_WORKERS,
        "only_low_conf": cfg.ONLY_LOW_CONF,
        "low_conf_max_support": cfg.LOW_CONF_MAX_SUPPORT,
        "only_raw_wrong": cfg.ONLY_RAW_WRONG,
        "use_raw_init": cfg.USE_RAW_INIT,
        "use_diagnostic": cfg.USE_DIAGNOSTIC,
        "diag_max_tokens": cfg.DIAG_MAX_TOKENS,
        "diag_temperature": cfg.DIAG_TEMPERATURE,
        "use_verified_notes": cfg.USE_VERIFIED_NOTES,
        "use_strict_equiv": cfg.USE_STRICT_EQUIV,
        "use_task_queue": cfg.USE_TASK_QUEUE,
        "task_queue_mode": cfg.TASK_QUEUE_MODE,
        "admission_max_tokens": cfg.ADMISSION_MAX_TOKENS,
        "admission_temperature": cfg.ADMISSION_TEMPERATURE,
        "use_llm_admission": cfg.USE_LLM_ADMISSION,
        "run_main_agent": cfg.RUN_MAIN_AGENT,
        "run_delm_lite": cfg.RUN_DELM_LITE,
    }

    return {
        "input": str(cfg.INPUT_PATH),
        "output": str(cfg.OUT_PATH),
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
