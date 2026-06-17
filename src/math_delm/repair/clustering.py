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

from src.math_delm.repair.equivalence import answer_equiv, answer_in_list
from src.math_delm.repair.answer_parser import is_valid_answer


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


def make_worker_confidence_map(worker_outputs: list[dict[str, Any]]) -> dict[int, float]:
    confidences = {}

    for output in worker_outputs:
        worker_id = cfg.to_int(output.get("worker_id"), None)
        if worker_id is None:
            continue

        parsed = output.get("parsed") or {}
        confidences[worker_id] = cfg.to_float(parsed.get("confidence"), 0.0)

    return confidences


def note_answer_matches(note_answer: str | None, candidate_answer: str | None) -> bool:
    note_answer = normalize_answer(note_answer)
    candidate_answer = normalize_answer(candidate_answer)
    if note_answer is None or candidate_answer is None:
        return False
    strict_result = strict_equivalence_check(note_answer, candidate_answer) if cfg.USE_STRICT_EQUIV else None
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
        worker_id = cfg.to_int(member.get("worker_id"), None)
        if worker_id is not None and worker_id in worker_confidences:
            member_confidences.append(worker_confidences[worker_id])

    support_count = cfg.to_int(cluster.get("support_count"), None)
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
            cfg.to_int(member.get("worker_id"), None)
            for member in cluster.get("members", [])
            if cfg.to_int(member.get("worker_id"), None) is not None
        ],
        **note_counts,
    }


def deterministic_cluster_sort_key(score: dict[str, Any]) -> tuple[int, int, int, float, float, int]:
    cluster_id = cfg.to_int(score.get("cluster_id"), None)
    if cluster_id is None:
        cluster_id = 10**9

    return (
        cfg.to_int(score.get("verified_block_count"), 0) or 0,
        -(cfg.to_int(score.get("verified_support_count"), 0) or 0),
        -(cfg.to_int(score.get("support_count"), 0) or 0),
        -cfg.to_float(score.get("avg_confidence"), 0.0),
        -cfg.to_float(score.get("max_confidence"), 0.0),
        cluster_id,
    )


def final_selector_sort_key(score: dict[str, Any]) -> tuple[int, int, int, float, float, float, int]:
    cluster_id = cfg.to_int(score.get("cluster_id"), None)
    if cluster_id is None:
        cluster_id = 10**9

    return (
        cfg.to_int(score.get("verified_block_count"), 0) or 0,
        -(cfg.to_int(score.get("verified_support_count"), 0) or 0),
        -(cfg.to_int(score.get("support_count"), 0) or 0),
        -cfg.to_float(score.get("avg_confidence"), 0.0),
        -cfg.to_float(score.get("adjusted_verifier_score"), 0.0),
        -cfg.to_float(score.get("max_confidence"), 0.0),
        cluster_id,
    )


def with_final_selection_score(
    score: dict[str, Any],
    verifier_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verifier_score = (
        cfg.to_float(verifier_evaluation.get("score"), 0.0)
        if isinstance(verifier_evaluation, dict)
        else cfg.to_float(score.get("verifier_score"), 0.0)
    )
    verified_support_count = cfg.to_int(score.get("verified_support_count"), 0) or 0
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
        worker_id = cfg.to_int(output.get("worker_id"), None)
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
        worker_id = cfg.to_int(member.get("worker_id"), None)
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
            sample_id = cfg.to_int(member.get("sample_id"), None)
            if sample_id is not None and 0 <= sample_id < len(valid_outputs):
                member["worker_id"] = valid_outputs[sample_id].get("worker_id")
                member["strategy"] = (valid_outputs[sample_id].get("parsed") or {}).get("strategy")

    return clusters
