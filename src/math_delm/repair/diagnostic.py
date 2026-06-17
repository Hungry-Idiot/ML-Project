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

from src.math_delm.llm.client import call_llm
from src.math_delm.repair.answer_parser import extract_json_object
from src.math_delm.repair.shared_context import get_rejected_answers_from_shared_context


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


def run_diagnostic_critic(
    client,
    case: dict[str, Any],
    wrong_answer: str | None,
    wrong_record: dict[str, Any] | None,
    rejected_answers: list[str | None],
    method_name: str,
) -> dict[str, Any]:
    from src.math_delm.prompts.diagnostic import build_diagnostic_prompt

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
        temperature=cfg.DIAG_TEMPERATURE,
        max_tokens=cfg.DIAG_MAX_TOKENS,
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
