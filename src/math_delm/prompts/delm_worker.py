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

from src.math_delm.repair.shared_context import make_shared_context_text, make_shared_diagnostic_feedback_text, make_verified_notes_text
from src.math_delm.agents.delm_lite import get_worker_role


def build_delm_worker_prompt(
    case: dict[str, Any],
    round_id: int,
    worker_id: int,
    shared_context: dict[str, Any],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    worker_role = get_worker_role(worker_id)
    strategy = cfg.STRATEGY_POOL[(round_id + worker_id - 1) % len(cfg.STRATEGY_POOL)]
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
