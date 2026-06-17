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

from src.math_delm.repair.shared_context import make_shared_context_text


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
