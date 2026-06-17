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

from src.math_delm.agents.main_agent import make_diagnostic_history_text, make_forbidden_answers_text, make_previous_attempts_text


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
    round_strategy = cfg.STRATEGY_POOL[(round_id - 1) % len(cfg.STRATEGY_POOL)]

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
