from __future__ import annotations

import json
import os
import time
from typing import Any

from src.math_delm.utils import (
    append_jsonl,
    get_client,
    load_done_ids,
    normalize_answer,
    read_jsonl,
    short_text,
)
from src.math_delm import config as cfg
from src.math_delm.agents.delm_lite import run_delm_lite_feedback_retry
from src.math_delm.agents.main_agent import case_raw_correct, run_main_agent_feedback_retry
from src.math_delm.evaluation.metrics import make_summary_json, method_result
from src.math_delm.evaluation.report import make_md_report


def should_include_case(case: dict[str, Any]) -> bool:
    if not cfg.ONLY_LOW_CONF:
        return True

    support = cfg.to_int(case.get("raw_selected_support"), 0)
    return support <= cfg.LOW_CONF_MAX_SUPPORT


def parse_case_ids_from_env() -> set[int] | None:
    raw = os.getenv("FEEDBACK_CASE_IDS", "").strip()

    if not raw:
        return None

    case_ids = set()

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        case_ids.add(int(item))

    return case_ids or None


def get_case_identity(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case.get("id"),
        "question_id": case.get("question_id"),
        "answer_type": case.get("answer_type"),
        "problem": case.get("problem"),
        "gold": case.get("gold"),
        "raw_selected_answer": normalize_answer(case.get("raw_selected_answer")),
        "raw_selected_support": case.get("raw_selected_support"),
        "raw_correct": case.get("raw_correct"),
        "oracle_correct": case.get("oracle_correct"),
    }


def run_case(client, case: dict[str, Any]) -> dict[str, Any] | None:
    identity = get_case_identity(case)

    record = {
        **identity,
        "benchmark": "oracle-feedback iterative repair",
        "settings": {
            "max_rounds": cfg.MAX_ROUNDS,
            "delm_workers": cfg.DELM_WORKERS,
            "max_tokens": cfg.MAX_TOKENS,
            "temperature": cfg.TEMPERATURE,
            "selector_temperature": cfg.SELECTOR_TEMPERATURE,
            "use_llm_selector": cfg.USE_LLM_SELECTOR,
            "only_low_conf": cfg.ONLY_LOW_CONF,
            "low_conf_max_support": cfg.LOW_CONF_MAX_SUPPORT,
            "only_raw_wrong": cfg.ONLY_RAW_WRONG,
            "use_raw_init": cfg.USE_RAW_INIT,
            "use_diagnostic": cfg.USE_DIAGNOSTIC,
            "diag_max_tokens": cfg.DIAG_MAX_TOKENS,
            "diag_temperature": cfg.DIAG_TEMPERATURE,
            "use_verified_notes": cfg.USE_VERIFIED_NOTES,
            "use_strict_equiv": cfg.USE_STRICT_EQUIV,
            "use_task_queue": cfg.USE_TASK_QUEUE,
            "task_queue_mode": cfg.TASK_QUEUE_MODE,
            "admission_max_tokens": cfg.ADMISSION_MAX_TOKENS,
            "admission_temperature": cfg.ADMISSION_TEMPERATURE,
            "use_llm_admission": cfg.USE_LLM_ADMISSION,
            "selector_mode": cfg.SELECTOR_MODE,
            "verifier_max_tokens": cfg.VERIFIER_MAX_TOKENS,
            "verifier_temperature": cfg.VERIFIER_TEMPERATURE,
        },
        "main_agent": None,
        "delm_lite": None,
    }

    if cfg.RUN_MAIN_AGENT:
        print("\n### Running Main-Agent Feedback Retry ###")
        main_result = run_main_agent_feedback_retry(client, case)
        if main_result is None:
            return None
        record["main_agent"] = main_result

    if cfg.RUN_DELM_LITE:
        print("\n### Running DELM-lite Feedback Retry ###")
        delm_result = run_delm_lite_feedback_retry(client, case)
        if delm_result is None:
            return None
        record["delm_lite"] = delm_result

    return record


def select_cases(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[int] | None]:
    cases.sort(key=lambda r: int(r["id"]))
    requested_case_ids = parse_case_ids_from_env()

    if requested_case_ids is not None:
        cases = [
            case for case in cases
            if cfg.to_int(case.get("id"), None) in requested_case_ids
        ]
    else:
        cases = [case for case in cases if should_include_case(case)]

        if cfg.ONLY_RAW_WRONG:
            cases = [
                case for case in cases
                if case_raw_correct(case) is False
            ]

        if cfg.LIMIT > 0:
            cases = cases[:cfg.LIMIT]

    if requested_case_ids is not None and cfg.ONLY_RAW_WRONG:
        cases = [
            case for case in cases
            if case_raw_correct(case) is False
        ]

    return cases, requested_case_ids


def print_settings(case_count: int, done_count: int, requested_case_ids: set[int] | None) -> None:
    print("Input:", cfg.INPUT_PATH)
    print("Output:", cfg.OUT_PATH)
    print("Error log:", cfg.ERROR_PATH)
    print("Report:", cfg.OUT_MD)
    print("Cases selected:", case_count)
    print("Already done:", done_count)
    print("Only low confidence:", cfg.ONLY_LOW_CONF)
    print("Low confidence max support:", cfg.LOW_CONF_MAX_SUPPORT)
    print("Only raw wrong:", cfg.ONLY_RAW_WRONG)
    print("Use raw init:", cfg.USE_RAW_INIT)
    print("Use diagnostic:", cfg.USE_DIAGNOSTIC)
    print("Diagnostic max tokens:", cfg.DIAG_MAX_TOKENS)
    print("Diagnostic temperature:", cfg.DIAG_TEMPERATURE)
    print("Use verified notes:", cfg.USE_VERIFIED_NOTES)
    print("Use strict equivalence:", cfg.USE_STRICT_EQUIV)
    print("Use task queue:", cfg.USE_TASK_QUEUE)
    print("Task queue mode:", cfg.TASK_QUEUE_MODE)
    print("Admission max tokens:", cfg.ADMISSION_MAX_TOKENS)
    print("Admission temperature:", cfg.ADMISSION_TEMPERATURE)
    print("Use LLM admission fallback:", cfg.USE_LLM_ADMISSION)
    print("Case ids filter:", sorted(requested_case_ids) if requested_case_ids is not None else "None")
    print("Max rounds:", cfg.MAX_ROUNDS)
    print("DELM workers:", cfg.DELM_WORKERS)
    print("Max tokens:", cfg.MAX_TOKENS)
    print("Temperature:", cfg.TEMPERATURE)
    print("Selector temperature:", cfg.SELECTOR_TEMPERATURE)
    print("Use LLM selector:", cfg.USE_LLM_SELECTOR)
    print("Selector mode:", cfg.SELECTOR_MODE)
    print("Verifier max tokens:", cfg.VERIFIER_MAX_TOKENS)
    print("Verifier temperature:", cfg.VERIFIER_TEMPERATURE)
    print("Run Main-Agent:", cfg.RUN_MAIN_AGENT)
    print("Run DELM-lite:", cfg.RUN_DELM_LITE)
    print("Limit:", "ignored by FEEDBACK_CASE_IDS" if requested_case_ids is not None else (cfg.LIMIT if cfg.LIMIT > 0 else "None"))


def write_final_outputs() -> dict[str, Any]:
    final_records = read_jsonl(cfg.OUT_PATH)
    final_records.sort(key=lambda r: int(r["id"]))

    cfg.OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    cfg.OUT_MD.write_text(make_md_report(final_records), encoding="utf-8")

    cfg.OUT_SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    summary_json = make_summary_json(final_records)
    cfg.OUT_SUMMARY_JSON.write_text(
        json.dumps(summary_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary_json


def print_final_summary(summary_json: dict[str, Any]) -> None:
    summary = summary_json["summary"]
    main_summary = summary["main_agent"]
    delm_summary = summary["delm_lite"]

    print("\n=== Feedback Repair Benchmark Results ===")
    print("Total completed:", summary["total"])
    print("Main-Agent solved:", main_summary["solved"], main_summary["solved_rate"])
    print("Main-Agent solved per minute:", main_summary["solved_per_minute"])
    print("Main-Agent tokens per solved:", main_summary["tokens_per_solved"])
    print("Main-Agent repeated wrong answers:", main_summary["repeated_wrong_answer_count"])
    print("Main-Agent duplicate forbidden answers:", main_summary["duplicate_forbidden_answer_count"])
    print("Main-Agent invalid answers:", main_summary["invalid_answer_count"])
    print("Main-Agent truncated answers:", main_summary["truncated_answer_count"])
    print("Main-Agent parser-invalid answers:", main_summary["parser_invalid_count"])
    print("Main-Agent diagnostic calls:", main_summary["diagnostic_calls"])
    print("Main-Agent diagnostic tokens:", main_summary["diagnostic_tokens"])
    print("Main-Agent verifier calls:", main_summary["verifier_calls"])
    print("Main-Agent verifier tokens:", main_summary["verifier_tokens"])
    print("DELM-lite solved:", delm_summary["solved"], delm_summary["solved_rate"])
    print("DELM-lite solved per minute:", delm_summary["solved_per_minute"])
    print("DELM-lite tokens per solved:", delm_summary["tokens_per_solved"])
    print("DELM-lite repeated wrong answers:", delm_summary["repeated_wrong_answer_count"])
    print("DELM-lite duplicate forbidden answers:", delm_summary["duplicate_forbidden_answer_count"])
    print("DELM-lite invalid answers:", delm_summary["invalid_answer_count"])
    print("DELM-lite truncated answers:", delm_summary["truncated_answer_count"])
    print("DELM-lite parser-invalid answers:", delm_summary["parser_invalid_count"])
    print("DELM-lite diagnostic calls:", delm_summary["diagnostic_calls"])
    print("DELM-lite diagnostic tokens:", delm_summary["diagnostic_tokens"])
    print("DELM-lite verifier calls:", delm_summary["verifier_calls"])
    print("DELM-lite verifier tokens:", delm_summary["verifier_tokens"])
    print("DELM-lite verified notes added:", delm_summary["verified_notes_added"])
    print("DELM-lite rejected notes:", delm_summary["rejected_notes_count"])
    print("DELM-lite uncertain notes:", delm_summary["uncertain_notes_count"])
    print("DELM-lite admission evaluations:", delm_summary["admission_evaluations"])
    print("DELM-lite admission calls:", delm_summary["admission_calls"])
    print("DELM-lite admission tokens:", delm_summary["admission_tokens"])
    print("DELM-lite strict false positives prevented:", delm_summary["strict_equiv_false_positives_prevented"])
    print("DELM-lite verified support selected:", delm_summary["verified_support_selected_count"])
    print("DELM-lite verified blocked candidates:", delm_summary["verified_blocked_candidate_count"])
    print("DELM minus Main-Agent solved count:", summary["delm_minus_main_solved"])
    print("DELM latent worker solved count:", delm_summary["latent_worker_solved"])

    print("\nSaved:")
    print("-", cfg.OUT_PATH)
    print("-", cfg.ERROR_PATH)
    print("-", cfg.OUT_MD)
    print("-", cfg.OUT_SUMMARY_JSON)


def main() -> None:
    if not cfg.INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Missing {cfg.INPUT_PATH}\n"
            "Please run `python scripts/prepare/analyze_sc3.py` first."
        )

    cases, requested_case_ids = select_cases(read_jsonl(cfg.INPUT_PATH))
    done_ids = load_done_ids(cfg.OUT_PATH)
    print_settings(len(cases), len(done_ids), requested_case_ids)
    client = get_client()

    for n, case in enumerate(cases, start=1):
        idx = int(case["id"])

        if idx in done_ids:
            continue

        print(
            f"\n===== Feedback Repair Case {n}/{len(cases)}, "
            f"id={idx}, qid={case.get('question_id')}, "
            f"type={case.get('answer_type')}, "
            f"support={case.get('raw_selected_support')} ====="
        )

        record = run_case(client, case)

        if record is None:
            continue

        append_jsonl(cfg.OUT_PATH, record)
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        print("\n--- Case summary ---")
        print("gold:", short_text(record.get("gold"), 120))
        print("main solved:", main_result.get("solved"))
        print("main final:", short_text(main_result.get("final_answer"), 120))
        print("main rounds:", main_result.get("rounds_used"))
        print("delm solved:", delm_result.get("solved"))
        print("delm final:", short_text(delm_result.get("final_answer"), 120))
        print("delm rounds:", delm_result.get("rounds_used"))
        print("delm latent worker solved:", delm_result.get("latent_worker_solved"))

        time.sleep(cfg.SLEEP_SECONDS)

    print_final_summary(write_final_outputs())


if __name__ == "__main__":
    main()
