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

from src.math_delm.repair.answer_parser import is_valid_answer
from src.math_delm.repair.equivalence import answer_equiv


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


def make_verified_notes_text(shared_context: dict[str, Any]) -> str:
    return format_verified_notes(shared_context.get("verified_notes", []))


def ensure_note_context(shared_context: dict[str, Any]) -> dict[str, Any]:
    shared_context.setdefault("verified_notes", [])
    shared_context.setdefault("rejected_notes", [])
    shared_context.setdefault("note_admission_log", [])
    return shared_context


def make_note_admission_settings(client) -> dict[str, Any]:
    return {
        "client": client,
        "admission_max_tokens": cfg.ADMISSION_MAX_TOKENS,
        "admission_temperature": cfg.ADMISSION_TEMPERATURE,
        "use_llm_admission_fallback": cfg.USE_LLM_ADMISSION,
    }


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

        admission_calls += cfg.to_int(admission.get("admission_calls"), 0) or 0
        admission_tokens += cfg.to_int(admission.get("admission_tokens"), 0) or 0
        admission_evaluations += cfg.to_int(admission.get("admission_evaluations"), 0) or 0

    return {
        "verified_notes": round_verified,
        "rejected_notes": round_rejected,
        "admission_results": round_admission_results,
        "admission_evaluations": admission_evaluations,
        "admission_calls": admission_calls,
        "admission_tokens": admission_tokens,
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
