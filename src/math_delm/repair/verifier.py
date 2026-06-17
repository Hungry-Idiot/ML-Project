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
from src.math_delm.prompts.verifier import build_candidate_verifier_prompt
from src.math_delm.repair.answer_parser import extract_json_object
from src.math_delm.repair.clustering import final_selector_sort_key, score_cluster, with_final_selection_score


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

    score = cfg.to_float(parsed.get("score"), 0.0)
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
        temperature=cfg.VERIFIER_TEMPERATURE,
        max_tokens=cfg.VERIFIER_MAX_TOKENS,
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
