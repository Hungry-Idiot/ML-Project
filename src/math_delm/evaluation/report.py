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

from src.math_delm.evaluation.metrics import make_summary_json, method_result


def make_md_report(records: list[dict[str, Any]]) -> str:
    records = sorted(records, key=lambda r: int(r["id"]))
    summary = make_summary_json(records)["summary"]

    main = summary["main_agent"]
    delm = summary["delm_lite"]

    lines = []

    lines.append("# Oracle-feedback Iterative Repair Benchmark")
    lines.append("")
    lines.append(f"- Input: `{cfg.INPUT_PATH}`")
    lines.append(f"- Output: `{cfg.OUT_PATH}`")
    lines.append(f"- Only low-confidence cases: `{cfg.ONLY_LOW_CONF}`")
    lines.append(f"- Low-confidence rule: `raw_selected_support <= {cfg.LOW_CONF_MAX_SUPPORT}`")
    lines.append(f"- Only raw-wrong cases: `{cfg.ONLY_RAW_WRONG}`")
    lines.append(f"- Use raw vote initialization: `{cfg.USE_RAW_INIT}`")
    lines.append(f"- Use diagnostic feedback: `{cfg.USE_DIAGNOSTIC}`")
    lines.append(f"- Diagnostic max tokens: `{cfg.DIAG_MAX_TOKENS}`")
    lines.append(f"- Diagnostic temperature: `{cfg.DIAG_TEMPERATURE}`")
    lines.append(f"- Use verified notes: `{cfg.USE_VERIFIED_NOTES}`")
    lines.append(f"- Use strict equivalence guard: `{cfg.USE_STRICT_EQUIV}`")
    lines.append(f"- Use task queue roles: `{cfg.USE_TASK_QUEUE}`")
    lines.append(f"- Task queue mode: `{cfg.TASK_QUEUE_MODE}`")
    lines.append(f"- Admission max tokens: `{cfg.ADMISSION_MAX_TOKENS}`")
    lines.append(f"- Admission temperature: `{cfg.ADMISSION_TEMPERATURE}`")
    lines.append(f"- Use LLM admission fallback: `{cfg.USE_LLM_ADMISSION}`")
    lines.append(f"- Max rounds per problem: `{cfg.MAX_ROUNDS}`")
    lines.append(f"- DELM workers per round: `{cfg.DELM_WORKERS}`")
    lines.append(f"- Max tokens per call: `{cfg.MAX_TOKENS}`")
    lines.append(f"- Worker/Main temperature: `{cfg.TEMPERATURE}`")
    lines.append(f"- Selector temperature: `{cfg.SELECTOR_TEMPERATURE}`")
    lines.append(f"- Use LLM selector: `{cfg.USE_LLM_SELECTOR}`")
    lines.append(f"- Selector mode: `{cfg.SELECTOR_MODE}`")
    lines.append(f"- Verifier max tokens: `{cfg.VERIFIER_MAX_TOKENS}`")
    lines.append(f"- Verifier temperature: `{cfg.VERIFIER_TEMPERATURE}`")
    lines.append("")
    lines.append("Oracle feedback only tells the model whether its submitted answer is incorrect. The gold answer is never shown in prompts.")
    lines.append("")

    lines.append("## Main Result")
    lines.append("")
    lines.append(md_table(
        [
            "Method",
            "Solved",
            "Total",
            "Solved rate",
            "Avg rounds to solve",
            "API calls",
            "Tokens / solved",
            "Wall-time / solved",
            "Solved / minute",
            "Repeated wrong answers",
            "Duplicate forbidden answers",
            "Invalid answers",
            "Truncated answers",
            "Parser-invalid answers",
            "Diagnostic calls",
            "Diagnostic tokens",
            "Verifier calls",
            "Verifier tokens",
            "Admission calls",
            "Admission evaluations",
            "Admission tokens",
            "Verified notes",
            "Rejected notes",
            "Uncertain notes",
        ],
        [
            [
                "Main-Agent Feedback Retry",
                main["solved"],
                main["total"],
                main["solved_rate"],
                main["avg_rounds_to_solve"],
                main["api_calls"],
                main["tokens_per_solved"],
                main["wall_time_per_solved"],
                main["solved_per_minute"],
                main["repeated_wrong_answer_count"],
                main["duplicate_forbidden_answer_count"],
                main["invalid_answer_count"],
                main["truncated_answer_count"],
                main["parser_invalid_count"],
                main["diagnostic_calls"],
                main["diagnostic_tokens"],
                main["verifier_calls"],
                main["verifier_tokens"],
                main["admission_calls"],
                main["admission_evaluations"],
                main["admission_tokens"],
                main["verified_notes_added"],
                main["rejected_notes_count"],
                main["uncertain_notes_count"],
            ],
            [
                "DELM-lite Feedback Retry",
                delm["solved"],
                delm["total"],
                delm["solved_rate"],
                delm["avg_rounds_to_solve"],
                delm["api_calls"],
                delm["tokens_per_solved"],
                delm["wall_time_per_solved"],
                delm["solved_per_minute"],
                delm["repeated_wrong_answer_count"],
                delm["duplicate_forbidden_answer_count"],
                delm["invalid_answer_count"],
                delm["truncated_answer_count"],
                delm["parser_invalid_count"],
                delm["diagnostic_calls"],
                delm["diagnostic_tokens"],
                delm["verifier_calls"],
                delm["verifier_tokens"],
                delm["admission_calls"],
                delm["admission_evaluations"],
                delm["admission_tokens"],
                delm["verified_notes_added"],
                delm["rejected_notes_count"],
                delm["uncertain_notes_count"],
            ],
        ],
    ))
    lines.append("")
    lines.append(f"- DELM minus Main-Agent solved count: **{summary['delm_minus_main_solved']}**")
    lines.append(f"- DELM latent worker solved count: **{delm.get('latent_worker_solved')}**")
    lines.append(f"- DELM verified support selected count: **{delm.get('verified_support_selected_count')}**")
    lines.append(f"- DELM verified blocked candidate count: **{delm.get('verified_blocked_candidate_count')}**")
    lines.append(f"- DELM strict equivalence false positives prevented: **{delm.get('strict_equiv_false_positives_prevented')}**")
    lines.append("")

    lines.append("## Accuracy by Answer Type")
    lines.append("")
    type_rows = []

    for answer_type, stats in summary["by_answer_type"].items():
        m = stats["main_agent"]
        d = stats["delm_lite"]
        type_rows.append([
            answer_type,
            stats["total"],
            m["solved"],
            d["solved"],
            m["solved_rate"],
            d["solved_rate"],
            d["solved"] - m["solved"],
        ])

    lines.append(md_table(
        [
            "answer_type",
            "total",
            "main_solved",
            "delm_solved",
            "main_rate",
            "delm_rate",
            "delm-main",
        ],
        type_rows,
    ))
    lines.append("")

    lines.append("## Case Table")
    lines.append("")
    case_rows = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        case_rows.append([
            record.get("id"),
            record.get("question_id"),
            record.get("answer_type"),
            record.get("raw_selected_support"),
            short_text(record.get("gold"), 80),
            main_result.get("solved"),
            short_text(main_result.get("final_answer"), 80),
            main_result.get("rounds_used"),
            delm_result.get("solved"),
            short_text(delm_result.get("final_answer"), 80),
            delm_result.get("rounds_used"),
            delm_result.get("latent_worker_solved"),
        ])

    lines.append(md_table(
        [
            "id",
            "qid",
            "type",
            "support",
            "gold",
            "main_solved",
            "main_final",
            "main_rounds",
            "delm_solved",
            "delm_final",
            "delm_rounds",
            "delm_latent",
        ],
        case_rows,
    ))
    lines.append("")

    lines.append("## Cases Solved by DELM but not Main-Agent")
    lines.append("")
    delm_only = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        if delm_result.get("solved") is True and main_result.get("solved") is not True:
            delm_only.append(record)

    if not delm_only:
        lines.append("No case was solved by DELM-lite only.")
        lines.append("")
    else:
        for record in delm_only:
            main_result = method_result(record, "main_agent")
            delm_result = method_result(record, "delm_lite")

            lines.append(f"### Case id={record.get('id')}, question_id={record.get('question_id')}")
            lines.append("")
            lines.append(f"- Gold: `{short_text(record.get('gold'), 200)}`")
            lines.append(f"- Main final: `{short_text(main_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM final: `{short_text(delm_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM rounds used: `{delm_result.get('rounds_used')}`")
            lines.append("")

    lines.append("## Cases Solved by Main-Agent but not DELM")
    lines.append("")
    main_only = []

    for record in records:
        main_result = method_result(record, "main_agent")
        delm_result = method_result(record, "delm_lite")

        if main_result.get("solved") is True and delm_result.get("solved") is not True:
            main_only.append(record)

    if not main_only:
        lines.append("No case was solved by Main-Agent only.")
        lines.append("")
    else:
        for record in main_only:
            main_result = method_result(record, "main_agent")
            delm_result = method_result(record, "delm_lite")

            lines.append(f"### Case id={record.get('id')}, question_id={record.get('question_id')}")
            lines.append("")
            lines.append(f"- Gold: `{short_text(record.get('gold'), 200)}`")
            lines.append(f"- Main final: `{short_text(main_result.get('final_answer'), 200)}`")
            lines.append(f"- DELM final: `{short_text(delm_result.get('final_answer'), 200)}`")
            lines.append(f"- Main rounds used: `{main_result.get('rounds_used')}`")
            lines.append("")

    return "\n".join(lines)
