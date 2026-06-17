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

from src.math_delm.repair.clustering import cluster_worker_evidence
from src.math_delm.repair.shared_context import make_shared_context_text


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
