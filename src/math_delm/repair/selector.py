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
from src.math_delm.prompts.selector import build_delm_selector_prompt
from src.math_delm.repair.answer_parser import extract_json_object, is_valid_answer, parse_answer_from_output
from src.math_delm.repair.clustering import (
    deterministic_cluster_sort_key,
    enrich_cluster_scores_with_verifier,
    filter_valid_non_rejected_clusters,
    final_selector_sort_key,
    make_worker_confidence_map,
    score_cluster,
    with_final_selection_score,
)
from src.math_delm.repair.equivalence import answer_in_list, verify_answer_with_details
from src.math_delm.repair.shared_context import get_rejected_answers_from_shared_context
from src.math_delm.repair.verifier import select_cluster_with_verifier


def parse_selected_cluster_id(parsed: dict[str, Any] | None, text: str | None = None) -> int | None:
    if parsed:
        for key in ["selected_cluster_id", "cluster_id"]:
            cid = cfg.to_int(parsed.get(key), None)
            if cid is not None:
                return cid

    if text:
        patterns = [
            r"selected_cluster_id[\"']?\s*[:=]\s*(\d+)",
            r"Selected\s*Cluster\s*:\s*(\d+)",
            r"Cluster\s*:\s*(\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return cfg.to_int(match.group(1), None)

    return None


def get_cluster_by_id(clusters: list[dict[str, Any]], cid: int | None) -> dict[str, Any] | None:
    if cid is None:
        return None

    for cluster in clusters:
        if cfg.to_int(cluster.get("cluster_id"), None) == cid:
            return cluster

    return None


def run_delm_selector(
    client,
    case: dict[str, Any],
    round_id: int,
    shared_context: dict[str, Any],
    worker_outputs: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    rejected_answers = get_rejected_answers_from_shared_context(shared_context)
    clusters = filter_valid_non_rejected_clusters(clusters, rejected_answers)
    worker_confidences = make_worker_confidence_map(worker_outputs)
    cluster_scores = [
        score_cluster(cluster, worker_confidences, shared_context)
        for cluster in clusters
    ]

    if not clusters:
        return {
            "selected_cluster_id": None,
            "original_selected_answer": None,
            "selected_answer": None,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "invalid_selected_answer": True,
            "correct": False,
            "strict_equivalence": {
                "strict_equiv_result": None,
                "original_equiv_result": False,
                "final_equiv_result": False,
                "use_strict_equiv": cfg.USE_STRICT_EQUIV,
            },
            "parsed": None,
            "raw_output": "",
            "cluster_scores": [],
            "selected_cluster_score": None,
            "selector_mode": cfg.SELECTOR_MODE,
            "verifier_evaluations": [],
            "selected_verifier_score": None,
            "selected_verifier_verdict": None,
            "all_verifier_rejected": False,
            "verified_support_count": 0,
            "verified_block_count": 0,
            "supporting_note_ids": [],
            "blocking_note_ids": [],
            "membership_values_verified": [],
            "completeness_evidence_present": False,
            "missing_verified_members": [],
            "extra_unverified_members": [],
            "set_support_type": "none",
            "final_selection_score": None,
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": None,
                "raw_output_tail": "",
            },
            "finish_reason": "no_valid_non_rejected_clusters",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": 0.0,
            "reason": "all candidate clusters were invalid or already rejected",
        }

    if cfg.SELECTOR_MODE == "deterministic":
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
        selected_cluster_score = sorted(cluster_scores, key=final_selector_sort_key)[0]
        selected_cluster = get_cluster_by_id(clusters, cfg.to_int(selected_cluster_score.get("cluster_id"), None))
        if selected_cluster is None:
            selected_cluster = clusters[0]
        selected_cluster_id = selected_cluster.get("cluster_id")
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

        print(f"--- DELM deterministic selector, round {round_id}/{cfg.MAX_ROUNDS} ---")
        print("selector answer:", short_text(selected_answer, 120))
        print("selector correct:", correct)

        return {
            "selected_cluster_id": selected_cluster_id,
            "original_selected_answer": selected_answer,
            "selected_answer": selected_answer,
            "invalid_selected_answer": False,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "correct": correct,
            "strict_equivalence": verification,
            "parsed": None,
            "raw_output": "",
            "cluster_scores": cluster_scores,
            "selected_cluster_score": selected_cluster_score,
            "selector_mode": "deterministic",
            "verifier_evaluations": [],
            "selected_verifier_score": None,
            "selected_verifier_verdict": None,
            "all_verifier_rejected": False,
            "verified_support_count": selected_cluster_score.get("verified_support_count", 0),
            "verified_block_count": selected_cluster_score.get("verified_block_count", 0),
            "supporting_note_ids": selected_cluster_score.get("supporting_note_ids", []),
            "blocking_note_ids": selected_cluster_score.get("blocking_note_ids", []),
            "membership_values_verified": selected_cluster_score.get("membership_values_verified", []),
            "completeness_evidence_present": selected_cluster_score.get("completeness_evidence_present", False),
            "missing_verified_members": selected_cluster_score.get("missing_verified_members", []),
            "extra_unverified_members": selected_cluster_score.get("extra_unverified_members", []),
            "set_support_type": selected_cluster_score.get("set_support_type", "none"),
            "final_selection_score": selected_cluster_score.get("final_selection_score"),
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": selected_answer,
                "raw_output_tail": "",
            },
            "finish_reason": "deterministic_selector",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": 0.0,
            "reason": "deterministic_selector: selected by support_count, avg_confidence, max_confidence",
        }

    if cfg.SELECTOR_MODE in {"verifier", "hybrid"}:
        selected_cluster, selected_evaluation, verifier_evaluations, all_verifier_rejected = (
            select_cluster_with_verifier(
                client=client,
                case=case,
                shared_context=shared_context,
                worker_outputs=worker_outputs,
                clusters=clusters,
                cluster_scores=cluster_scores,
                rejected_answers=rejected_answers,
            )
        )
        selected_cluster_id = selected_cluster.get("cluster_id")
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
        selected_cluster_score = with_final_selection_score(
            score_cluster(selected_cluster, worker_confidences, shared_context),
            selected_evaluation,
        )
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores, verifier_evaluations)
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

        print(f"--- DELM {cfg.SELECTOR_MODE} selector, round {round_id}/{cfg.MAX_ROUNDS} ---")
        print("selector answer:", short_text(selected_answer, 120))
        print("selector correct:", correct)
        print("selector verifier score:", selected_evaluation.get("score"))
        print("selector verifier verdict:", selected_evaluation.get("verdict"))

        return {
            "selected_cluster_id": selected_cluster_id,
            "original_selected_answer": selected_answer,
            "selected_answer": selected_answer,
            "invalid_selected_answer": False,
            "selector_selected_rejected_answer": False,
            "fallback_selected_non_rejected": False,
            "correct": correct,
            "strict_equivalence": verification,
            "parsed": None,
            "raw_output": "",
            "cluster_scores": cluster_scores,
            "selected_cluster_score": selected_cluster_score,
            "selector_mode": cfg.SELECTOR_MODE,
            "verifier_evaluations": verifier_evaluations,
            "selected_verifier_score": selected_evaluation.get("score"),
            "selected_verifier_verdict": selected_evaluation.get("verdict"),
            "all_verifier_rejected": all_verifier_rejected,
            "verified_support_count": selected_cluster_score.get("verified_support_count", 0),
            "verified_block_count": selected_cluster_score.get("verified_block_count", 0),
            "supporting_note_ids": selected_cluster_score.get("supporting_note_ids", []),
            "blocking_note_ids": selected_cluster_score.get("blocking_note_ids", []),
            "membership_values_verified": selected_cluster_score.get("membership_values_verified", []),
            "completeness_evidence_present": selected_cluster_score.get("completeness_evidence_present", False),
            "missing_verified_members": selected_cluster_score.get("missing_verified_members", []),
            "extra_unverified_members": selected_cluster_score.get("extra_unverified_members", []),
            "set_support_type": selected_cluster_score.get("set_support_type", "none"),
            "final_selection_score": selected_cluster_score.get("final_selection_score"),
            "parser_debug": {
                "parsed_json": False,
                "parsed_keys": [],
                "extracted_answer": selected_answer,
                "raw_output_tail": "",
            },
            "finish_reason": f"{cfg.SELECTOR_MODE}_selector",
            "usage": {},
            "api_call": False,
            "wall_time_seconds": sum(
                cfg.to_float(evaluation.get("wall_time_seconds"), 0.0)
                for evaluation in verifier_evaluations
            ),
            "reason": (
                f"{cfg.SELECTOR_MODE}_selector: selected by verifier score"
                " with deterministic tie-break"
            ),
        }

    print(f"--- DELM selector, round {round_id}/{cfg.MAX_ROUNDS} ---")

    prompt = build_delm_selector_prompt(
        case=case,
        round_id=round_id,
        shared_context=shared_context,
        worker_outputs=worker_outputs,
        clusters=clusters,
    )

    result = call_llm(client, prompt, temperature=cfg.SELECTOR_TEMPERATURE)

    if result.get("error") is not None or result.get("finish_reason") == "api_error":
        append_jsonl(cfg.ERROR_PATH, {
            "id": case.get("id"),
            "method": "delm_lite",
            "round": round_id,
            "stage": "selector",
            "result": result,
        })
        print("[SKIP] DELM selector API error.")
        return None

    parsed = extract_json_object(result.get("content"))
    selected_cluster_id = parse_selected_cluster_id(parsed, result.get("content"))
    selected_answer = parse_answer_from_output(result.get("content"), parsed)
    parser_selected_answer = selected_answer

    selected_cluster = get_cluster_by_id(clusters, selected_cluster_id)
    if selected_cluster is not None:
        selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))

    selected_cluster_score = None
    if selected_cluster is not None:
        cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
        selected_cluster_score = with_final_selection_score(
            score_cluster(selected_cluster, worker_confidences, shared_context)
        )

    original_selected_answer = selected_answer
    invalid_selected_answer = not is_valid_answer(selected_answer)
    selector_selected_rejected_answer = (
        False if invalid_selected_answer else answer_in_list(selected_answer, rejected_answers)
    )
    fallback_selected_non_rejected = False
    reason = (parsed or {}).get("reason") if isinstance(parsed, dict) else None
    finish_reason = result.get("finish_reason")

    if invalid_selected_answer or selector_selected_rejected_answer:
        fallback_cluster = clusters[0] if clusters else None
        if fallback_cluster is not None:
            selected_cluster = fallback_cluster
            selected_cluster_id = fallback_cluster.get("cluster_id")
            selected_answer = normalize_answer(fallback_cluster.get("canonical_answer"))
            fallback_selected_non_rejected = True
            if invalid_selected_answer:
                reason = "selector selected an invalid answer; fell back to first non-rejected cluster"
            else:
                reason = "selector selected a rejected answer; fell back to first non-rejected cluster"
        else:
            selected_cluster = None
            selected_cluster_id = None
            selected_answer = None
            finish_reason = "no_valid_non_rejected_clusters"
            reason = "all candidate clusters were invalid or already rejected"

    cluster_scores = enrich_cluster_scores_with_verifier(cluster_scores)
    selected_cluster_score = (
        with_final_selection_score(score_cluster(selected_cluster, worker_confidences, shared_context))
        if selected_cluster is not None else None
    )
    if selected_answer is None:
        correct = False
        verification = {
            "strict_equiv_result": None,
            "original_equiv_result": False,
            "final_equiv_result": False,
            "use_strict_equiv": cfg.USE_STRICT_EQUIV,
        }
    else:
        correct, verification = verify_answer_with_details(case.get("gold"), selected_answer)

    print("selector answer:", short_text(selected_answer, 120))
    print("selector correct:", correct)
    print("selector invalid answer:", invalid_selected_answer)
    print("selector selected rejected answer:", selector_selected_rejected_answer)
    print("selector fallback non-rejected:", fallback_selected_non_rejected)

    return {
        "selected_cluster_id": selected_cluster_id,
        "original_selected_answer": original_selected_answer,
        "selected_answer": selected_answer,
        "invalid_selected_answer": invalid_selected_answer,
        "selector_selected_rejected_answer": selector_selected_rejected_answer,
        "fallback_selected_non_rejected": fallback_selected_non_rejected,
        "correct": correct,
        "strict_equivalence": verification,
        "parsed": parsed,
        "raw_output": result.get("content", ""),
        "cluster_scores": cluster_scores,
        "selected_cluster_score": selected_cluster_score,
        "selector_mode": "llm",
        "verifier_evaluations": [],
        "selected_verifier_score": None,
        "selected_verifier_verdict": None,
        "all_verifier_rejected": False,
        "verified_support_count": (selected_cluster_score or {}).get("verified_support_count", 0),
        "verified_block_count": (selected_cluster_score or {}).get("verified_block_count", 0),
        "supporting_note_ids": (selected_cluster_score or {}).get("supporting_note_ids", []),
        "blocking_note_ids": (selected_cluster_score or {}).get("blocking_note_ids", []),
        "membership_values_verified": (selected_cluster_score or {}).get("membership_values_verified", []),
        "completeness_evidence_present": (selected_cluster_score or {}).get("completeness_evidence_present", False),
        "missing_verified_members": (selected_cluster_score or {}).get("missing_verified_members", []),
        "extra_unverified_members": (selected_cluster_score or {}).get("extra_unverified_members", []),
        "set_support_type": (selected_cluster_score or {}).get("set_support_type", "none"),
        "final_selection_score": (selected_cluster_score or {}).get("final_selection_score"),
        "parser_debug": {
            "parsed_json": parsed is not None,
            "parsed_keys": list(parsed.keys()) if parsed else [],
            "extracted_answer": parser_selected_answer,
            "raw_output_tail": tail_text(result.get("content", ""), 500),
        },
        "finish_reason": finish_reason,
        "usage": result.get("usage"),
        "api_call": True,
        "wall_time_seconds": result.get("wall_time_seconds"),
        "reason": reason,
    }
