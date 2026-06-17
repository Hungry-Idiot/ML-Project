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

from src.math_delm.repair.shared_context import get_rejected_answers_from_shared_context
from src.math_delm.repair.diagnostic import wrong_record_reason


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
