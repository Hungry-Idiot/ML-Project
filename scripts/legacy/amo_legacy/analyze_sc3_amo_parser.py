import csv
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    safe_verify,
    read_jsonl,
    write_jsonl,
    choose_raw_majority,
    cluster_answers,
    choose_from_clusters,
    normalize_answer,
    pct,
    short_text,
    tail_text,
    md_table,
)


SC3_PATH = Path("outputs/amo_parser_sc3.jsonl")
SINGLE_PATH = Path("outputs/amo_parser_single.jsonl")
DATA_PATH = Path("data/AMO-Bench/test.jsonl")

OUT_MD = Path("outputs/amo_parser_sc3_analysis.md")
OUT_JSON = Path("outputs/amo_parser_sc3_analysis.json")
OUT_CASES_JSONL = Path("outputs/amo_parser_sc3_analysis_cases.jsonl")
OUT_CASES_CSV = Path("outputs/amo_parser_sc3_analysis_cases.csv")


_verify_cache: dict[tuple[str, str | None], bool] = {}


def verify_answer(gold: str, pred: str | None) -> bool:
    key = (gold, pred)
    if key not in _verify_cache:
        _verify_cache[key] = safe_verify(gold, pred)
    return _verify_cache[key]


def normalize_raw(ans: str | None) -> str | None:
    """
    RawVote 只做最小清理，不做数学归一化。
    """
    return normalize_answer(ans)


def get_pred_answers(ex: dict[str, Any]) -> list[str | None]:
    """
    兼容两种结构：
    1. pred_answers: [...]
    2. sample_records: [{"pred_answer": ...}, ...]
    """
    if "pred_answers" in ex and isinstance(ex["pred_answers"], list):
        return [normalize_raw(x) for x in ex["pred_answers"]]

    sample_records = ex.get("sample_records", [])
    return [normalize_raw(s.get("pred_answer")) for s in sample_records]


def get_sample_records(ex: dict[str, Any]) -> list[dict[str, Any]]:
    sample_records = ex.get("sample_records", [])
    if isinstance(sample_records, list):
        return sample_records
    return []


def choose_equiv_cluster(pred_answers: list[str | None]) -> tuple[str | None, int, list[dict[str, Any]]]:
    clusters = cluster_answers(pred_answers)
    return choose_from_clusters(clusters)


def usage_value(sample_records: list[dict[str, Any]], key: str) -> int:
    total = 0
    for s in sample_records:
        usage = s.get("usage")
        if isinstance(usage, dict):
            v = usage.get(key)
            if isinstance(v, int):
                total += v
    return total


def finish_reasons(sample_records: list[dict[str, Any]]) -> list[str | None]:
    return [s.get("finish_reason") for s in sample_records]


def build_data_lookup() -> dict[int, dict[str, Any]]:
    data = read_jsonl(DATA_PATH)
    return {ex["id"]: ex for ex in data if "id" in ex}


def build_single_lookup() -> dict[int, dict[str, Any]]:
    single = read_jsonl(SINGLE_PATH)
    return {ex["id"]: ex for ex in single if "id" in ex}


def add_binary_counter(counter: Counter, name: str, value: bool) -> None:
    if value:
        counter[name] += 1


def summarize_group(cases: list[dict[str, Any]], group_key: str, metric_key: str) -> list[dict[str, Any]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for c in cases:
        groups[c.get(group_key)].append(c)

    rows = []
    for k, items in sorted(groups.items(), key=lambda x: str(x[0])):
        total = len(items)
        correct = sum(1 for c in items if c.get(metric_key) is True)
        rows.append({
            group_key: k,
            "total": total,
            "correct": correct,
            "accuracy": pct(correct, total),
        })
    return rows


def main():
    if not SC3_PATH.exists():
        raise FileNotFoundError(f"SC3 result file not found: {SC3_PATH}")

    sc3_records = read_jsonl(SC3_PATH)
    data_lookup = build_data_lookup()
    single_lookup = build_single_lookup()

    cases: list[dict[str, Any]] = []

    global_counter = Counter()
    finish_counter = Counter()
    answer_type_counter = Counter()
    support_counter = Counter()
    equiv_support_counter = Counter()
    raw_unique_counter = Counter()
    equiv_cluster_counter = Counter()

    sample_position_total = Counter()
    sample_position_correct = Counter()
    sample_position_parsed = Counter()

    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    total_sample_calls = 0

    for ex in sc3_records:
        idx = ex["id"]
        gold = ex.get("gold")
        answer_type = ex.get("answer_type")
        pred_answers = get_pred_answers(ex)
        sample_records = get_sample_records(ex)

        data_ex = data_lookup.get(idx, {})
        single_ex = single_lookup.get(idx)

        raw_selected, raw_support, vote_counts = choose_raw_majority(pred_answers)
        raw_correct = verify_answer(gold, raw_selected)

        sample_correct_flags = [verify_answer(gold, a) for a in pred_answers]
        sample_parsed_flags = [normalize_raw(a) is not None for a in pred_answers]

        oracle_correct = any(sample_correct_flags)
        num_correct_samples = sum(sample_correct_flags)
        num_parsed_samples = sum(sample_parsed_flags)
        num_valid_answers = sum(1 for a in pred_answers if normalize_raw(a) is not None)

        valid_raw_answers = [normalize_raw(a) for a in pred_answers if normalize_raw(a) is not None]
        raw_unique_count = len(set(valid_raw_answers))
        raw_disagreement = raw_unique_count > 1

        equiv_selected, equiv_support, equiv_clusters = choose_equiv_cluster(pred_answers)
        equiv_correct = verify_answer(gold, equiv_selected)
        equiv_cluster_count = len(equiv_clusters)
        equiv_disagreement = equiv_cluster_count > 1

        raw_disagree_but_one_equiv_cluster = raw_disagreement and equiv_cluster_count == 1
        raw_vote_missed_oracle = oracle_correct and not raw_correct
        equiv_recovers_raw = equiv_correct and not raw_correct
        raw_beats_equiv = raw_correct and not equiv_correct

        no_valid_answer = num_valid_answers == 0
        all_samples_correct = num_correct_samples == len(pred_answers) and len(pred_answers) > 0
        all_samples_wrong = num_correct_samples == 0 and num_valid_answers > 0
        unanimous_raw = raw_support == len(pred_answers) and len(pred_answers) > 0
        unanimous_wrong = unanimous_raw and not raw_correct
        majority_wrong = raw_support >= 2 and not raw_correct
        no_majority = raw_support <= 1

        single_pred = None
        single_correct = None
        single_parse_fail = None

        if single_ex is not None:
            single_pred = normalize_raw(single_ex.get("pred_answer"))
            single_correct = verify_answer(gold, single_pred)
            single_parse_fail = single_pred is None

        sc3_recovers_single = (
            single_correct is False and raw_correct is True
            if single_correct is not None else False
        )
        sc3_regresses_single = (
            single_correct is True and raw_correct is False
            if single_correct is not None else False
        )
        oracle_recovers_single = (
            single_correct is False and oracle_correct is True
            if single_correct is not None else False
        )

        reasons = finish_reasons(sample_records)

        for r in reasons:
            finish_counter[r] += 1

        for pos, flag in enumerate(sample_correct_flags):
            sample_position_total[pos] += 1
            if flag:
                sample_position_correct[pos] += 1

        for pos, flag in enumerate(sample_parsed_flags):
            if flag:
                sample_position_parsed[pos] += 1

        prompt_tokens = usage_value(sample_records, "prompt_tokens")
        completion_tokens = usage_value(sample_records, "completion_tokens")
        tokens = usage_value(sample_records, "total_tokens")

        total_prompt_tokens += prompt_tokens
        total_completion_tokens += completion_tokens
        total_tokens += tokens
        total_sample_calls += len(sample_records)

        answer_type_counter[answer_type] += 1
        support_counter[raw_support] += 1
        equiv_support_counter[equiv_support] += 1
        raw_unique_counter[raw_unique_count] += 1
        equiv_cluster_counter[equiv_cluster_count] += 1

        add_binary_counter(global_counter, "raw_correct", raw_correct)
        add_binary_counter(global_counter, "oracle_correct", oracle_correct)
        add_binary_counter(global_counter, "equiv_correct", equiv_correct)
        add_binary_counter(global_counter, "raw_disagreement", raw_disagreement)
        add_binary_counter(global_counter, "equiv_disagreement", equiv_disagreement)
        add_binary_counter(global_counter, "raw_disagree_but_one_equiv_cluster", raw_disagree_but_one_equiv_cluster)
        add_binary_counter(global_counter, "raw_vote_missed_oracle", raw_vote_missed_oracle)
        add_binary_counter(global_counter, "equiv_recovers_raw", equiv_recovers_raw)
        add_binary_counter(global_counter, "raw_beats_equiv", raw_beats_equiv)
        add_binary_counter(global_counter, "no_valid_answer", no_valid_answer)
        add_binary_counter(global_counter, "all_samples_correct", all_samples_correct)
        add_binary_counter(global_counter, "all_samples_wrong", all_samples_wrong)
        add_binary_counter(global_counter, "unanimous_raw", unanimous_raw)
        add_binary_counter(global_counter, "unanimous_wrong", unanimous_wrong)
        add_binary_counter(global_counter, "majority_wrong", majority_wrong)
        add_binary_counter(global_counter, "no_majority", no_majority)
        add_binary_counter(global_counter, "sc3_recovers_single", sc3_recovers_single)
        add_binary_counter(global_counter, "sc3_regresses_single", sc3_regresses_single)
        add_binary_counter(global_counter, "oracle_recovers_single", oracle_recovers_single)

        case = {
            "id": idx,
            "question_id": ex.get("question_id"),
            "answer_type": answer_type,
            "problem": data_ex.get("problem", ex.get("problem", "")),
            "gold": gold,

            "single_pred_answer": single_pred,
            "single_correct": single_correct,
            "single_parse_fail": single_parse_fail,

            "pred_answers": pred_answers,
            "sample_correct_flags": sample_correct_flags,
            "num_correct_samples": num_correct_samples,
            "num_parsed_samples": num_parsed_samples,

            "raw_selected_answer": raw_selected,
            "raw_selected_support": raw_support,
            "raw_vote_counts": vote_counts,
            "raw_correct": raw_correct,
            "raw_unique_count": raw_unique_count,
            "raw_disagreement": raw_disagreement,

            "oracle_correct": oracle_correct,

            "equiv_selected_answer": equiv_selected,
            "equiv_selected_support": equiv_support,
            "equiv_correct": equiv_correct,
            "equiv_cluster_count": equiv_cluster_count,
            "equiv_clusters": equiv_clusters,
            "equiv_disagreement": equiv_disagreement,

            "raw_disagree_but_one_equiv_cluster": raw_disagree_but_one_equiv_cluster,
            "raw_vote_missed_oracle": raw_vote_missed_oracle,
            "equiv_recovers_raw": equiv_recovers_raw,
            "raw_beats_equiv": raw_beats_equiv,
            "no_valid_answer": no_valid_answer,
            "all_samples_correct": all_samples_correct,
            "all_samples_wrong": all_samples_wrong,
            "unanimous_raw": unanimous_raw,
            "unanimous_wrong": unanimous_wrong,
            "majority_wrong": majority_wrong,
            "no_majority": no_majority,

            "sc3_recovers_single": sc3_recovers_single,
            "sc3_regresses_single": sc3_regresses_single,
            "oracle_recovers_single": oracle_recovers_single,

            "finish_reasons": reasons,
            "prompt_tokens_sum": prompt_tokens,
            "completion_tokens_sum": completion_tokens,
            "total_tokens_sum": tokens,

            "sample_output_tails": [
                tail_text(s.get("raw_output"), 1000)
                for s in sample_records
            ],
        }

        cases.append(case)

    total = len(cases)
    single_available = any(c.get("single_correct") is not None for c in cases)
    single_eval_cases = [c for c in cases if c.get("single_correct") is not None]

    single_correct = sum(1 for c in single_eval_cases if c.get("single_correct") is True)

    support_rows = summarize_group(cases, "raw_selected_support", "raw_correct")
    equiv_support_rows = summarize_group(cases, "equiv_selected_support", "equiv_correct")
    type_raw_rows = summarize_group(cases, "answer_type", "raw_correct")
    type_oracle_rows = summarize_group(cases, "answer_type", "oracle_correct")
    type_equiv_rows = summarize_group(cases, "answer_type", "equiv_correct")

    summary = {
        "input_file": str(SC3_PATH),
        "single_file": str(SINGLE_PATH) if SINGLE_PATH.exists() else None,
        "total": total,

        "single_cot": {
            "available": single_available,
            "total": len(single_eval_cases),
            "correct": single_correct,
            "accuracy": pct(single_correct, len(single_eval_cases)),
        },

        "sc3_raw_vote": {
            "correct": global_counter["raw_correct"],
            "accuracy": pct(global_counter["raw_correct"], total),
            "parse_fail": global_counter["no_valid_answer"],
            "parse_success": pct(total - global_counter["no_valid_answer"], total),
        },

        "oracle_at_3": {
            "correct": global_counter["oracle_correct"],
            "accuracy": pct(global_counter["oracle_correct"], total),
            "raw_vote_missed_oracle": global_counter["raw_vote_missed_oracle"],
        },

        "sc3_equiv_cluster": {
            "correct": global_counter["equiv_correct"],
            "accuracy": pct(global_counter["equiv_correct"], total),
            "equiv_recovers_raw": global_counter["equiv_recovers_raw"],
            "raw_beats_equiv": global_counter["raw_beats_equiv"],
        },

        "disagreement": {
            "raw_disagreement": global_counter["raw_disagreement"],
            "raw_disagreement_rate": pct(global_counter["raw_disagreement"], total),
            "equiv_disagreement": global_counter["equiv_disagreement"],
            "equiv_disagreement_rate": pct(global_counter["equiv_disagreement"], total),
            "raw_disagree_but_one_equiv_cluster": global_counter["raw_disagree_but_one_equiv_cluster"],
        },

        "selection_diagnostics": {
            "no_majority_support_le_1": global_counter["no_majority"],
            "majority_wrong_support_ge_2": global_counter["majority_wrong"],
            "unanimous_raw": global_counter["unanimous_raw"],
            "unanimous_wrong": global_counter["unanimous_wrong"],
            "all_samples_wrong": global_counter["all_samples_wrong"],
            "all_samples_correct": global_counter["all_samples_correct"],
        },

        "single_vs_sc3": {
            "sc3_recovers_single": global_counter["sc3_recovers_single"],
            "sc3_regresses_single": global_counter["sc3_regresses_single"],
            "oracle_recovers_single": global_counter["oracle_recovers_single"],
        },

        "distributions": {
            "answer_type": dict(answer_type_counter),
            "finish_reason_sample_level": dict(finish_counter),
            "raw_selected_support": dict(support_counter),
            "equiv_selected_support": dict(equiv_support_counter),
            "raw_unique_count": dict(raw_unique_counter),
            "equiv_cluster_count": dict(equiv_cluster_counter),
        },

        "token_usage": {
            "total_sample_calls": total_sample_calls,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "avg_prompt_tokens_per_call": total_prompt_tokens / total_sample_calls if total_sample_calls else None,
            "avg_completion_tokens_per_call": total_completion_tokens / total_sample_calls if total_sample_calls else None,
            "avg_total_tokens_per_call": total_tokens / total_sample_calls if total_sample_calls else None,
        },

        "sample_position_stats": {
            str(pos): {
                "total": sample_position_total[pos],
                "parsed": sample_position_parsed[pos],
                "correct": sample_position_correct[pos],
                "parse_success": pct(sample_position_parsed[pos], sample_position_total[pos]),
                "accuracy": pct(sample_position_correct[pos], sample_position_total[pos]),
            }
            for pos in sorted(sample_position_total)
        },

        "group_stats": {
            "raw_accuracy_by_support": support_rows,
            "equiv_accuracy_by_support": equiv_support_rows,
            "raw_accuracy_by_answer_type": type_raw_rows,
            "oracle_accuracy_by_answer_type": type_oracle_rows,
            "equiv_accuracy_by_answer_type": type_equiv_rows,
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    write_jsonl(OUT_CASES_JSONL, cases)

    with OUT_CASES_CSV.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "id",
            "question_id",
            "answer_type",
            "single_correct",
            "raw_correct",
            "oracle_correct",
            "equiv_correct",
            "raw_vote_missed_oracle",
            "equiv_recovers_raw",
            "sc3_recovers_single",
            "sc3_regresses_single",
            "raw_selected_support",
            "equiv_selected_support",
            "raw_unique_count",
            "equiv_cluster_count",
            "gold",
            "single_pred_answer",
            "raw_selected_answer",
            "equiv_selected_answer",
            "pred_answers",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for c in cases:
            writer.writerow({
                "id": c["id"],
                "question_id": c["question_id"],
                "answer_type": c["answer_type"],
                "single_correct": c["single_correct"],
                "raw_correct": c["raw_correct"],
                "oracle_correct": c["oracle_correct"],
                "equiv_correct": c["equiv_correct"],
                "raw_vote_missed_oracle": c["raw_vote_missed_oracle"],
                "equiv_recovers_raw": c["equiv_recovers_raw"],
                "sc3_recovers_single": c["sc3_recovers_single"],
                "sc3_regresses_single": c["sc3_regresses_single"],
                "raw_selected_support": c["raw_selected_support"],
                "equiv_selected_support": c["equiv_selected_support"],
                "raw_unique_count": c["raw_unique_count"],
                "equiv_cluster_count": c["equiv_cluster_count"],
                "gold": short_text(c["gold"], 300),
                "single_pred_answer": short_text(c["single_pred_answer"], 200),
                "raw_selected_answer": short_text(c["raw_selected_answer"], 200),
                "equiv_selected_answer": short_text(c["equiv_selected_answer"], 200),
                "pred_answers": short_text(c["pred_answers"], 500),
            })

    md_lines = []

    md_lines.append("# AMO-P SC3 Analysis")
    md_lines.append("")
    md_lines.append(f"- Input SC3 file: `{SC3_PATH}`")
    md_lines.append(f"- Single-CoT file: `{SINGLE_PATH}`" if SINGLE_PATH.exists() else "- Single-CoT file: not found")
    md_lines.append(f"- Total problems: **{total}**")
    md_lines.append("")

    md_lines.append("## Main Results")
    rows = [
        ["Single-CoT", single_correct if single_available else "N/A", len(single_eval_cases) if single_available else "N/A", pct(single_correct, len(single_eval_cases)) if single_available else "N/A"],
        ["SC3-RawVote", global_counter["raw_correct"], total, pct(global_counter["raw_correct"], total)],
        ["Oracle@3", global_counter["oracle_correct"], total, pct(global_counter["oracle_correct"], total)],
        ["SC3-EquivCluster", global_counter["equiv_correct"], total, pct(global_counter["equiv_correct"], total)],
    ]
    md_lines.append(md_table(["Method", "Correct", "Total", "Accuracy"], rows))
    md_lines.append("")

    md_lines.append("## Key Diagnostics")
    rows = [
        ["Raw disagreement problems", global_counter["raw_disagreement"], pct(global_counter["raw_disagreement"], total)],
        ["Equivalent-cluster disagreement problems", global_counter["equiv_disagreement"], pct(global_counter["equiv_disagreement"], total)],
        ["Raw disagreement but one equivalent cluster", global_counter["raw_disagree_but_one_equiv_cluster"], pct(global_counter["raw_disagree_but_one_equiv_cluster"], total)],
        ["RawVote wrong but Oracle@3 correct", global_counter["raw_vote_missed_oracle"], pct(global_counter["raw_vote_missed_oracle"], total)],
        ["EquivCluster correct while RawVote wrong", global_counter["equiv_recovers_raw"], pct(global_counter["equiv_recovers_raw"], total)],
        ["RawVote correct while EquivCluster wrong", global_counter["raw_beats_equiv"], pct(global_counter["raw_beats_equiv"], total)],
        ["No majority, selected_support <= 1", global_counter["no_majority"], pct(global_counter["no_majority"], total)],
        ["Majority wrong, selected_support >= 2", global_counter["majority_wrong"], pct(global_counter["majority_wrong"], total)],
        ["Unanimous raw answers", global_counter["unanimous_raw"], pct(global_counter["unanimous_raw"], total)],
        ["Unanimous but wrong", global_counter["unanimous_wrong"], pct(global_counter["unanimous_wrong"], total)],
        ["All samples wrong", global_counter["all_samples_wrong"], pct(global_counter["all_samples_wrong"], total)],
        ["All samples correct", global_counter["all_samples_correct"], pct(global_counter["all_samples_correct"], total)],
    ]
    md_lines.append(md_table(["Metric", "Count", "Rate"], rows))
    md_lines.append("")

    if single_available:
        md_lines.append("## Single-CoT vs SC3")
        rows = [
            ["SC3 recovers Single-CoT failure", global_counter["sc3_recovers_single"], pct(global_counter["sc3_recovers_single"], total)],
            ["SC3 regresses from Single-CoT success", global_counter["sc3_regresses_single"], pct(global_counter["sc3_regresses_single"], total)],
            ["Oracle@3 recovers Single-CoT failure", global_counter["oracle_recovers_single"], pct(global_counter["oracle_recovers_single"], total)],
        ]
        md_lines.append(md_table(["Metric", "Count", "Rate"], rows))
        md_lines.append("")

    md_lines.append("## RawVote Accuracy by selected_support")
    md_lines.append(md_table(
        ["selected_support", "Total", "Correct", "Accuracy"],
        [[r["raw_selected_support"], r["total"], r["correct"], r["accuracy"]] for r in support_rows]
    ))
    md_lines.append("")

    md_lines.append("## EquivCluster Accuracy by selected_support")
    md_lines.append(md_table(
        ["equiv_selected_support", "Total", "Correct", "Accuracy"],
        [[r["equiv_selected_support"], r["total"], r["correct"], r["accuracy"]] for r in equiv_support_rows]
    ))
    md_lines.append("")

    md_lines.append("## Accuracy by answer_type")
    md_lines.append("### RawVote")
    md_lines.append(md_table(
        ["answer_type", "Total", "Correct", "Accuracy"],
        [[r["answer_type"], r["total"], r["correct"], r["accuracy"]] for r in type_raw_rows]
    ))
    md_lines.append("")
    md_lines.append("### Oracle@3")
    md_lines.append(md_table(
        ["answer_type", "Total", "Correct", "Accuracy"],
        [[r["answer_type"], r["total"], r["correct"], r["accuracy"]] for r in type_oracle_rows]
    ))
    md_lines.append("")
    md_lines.append("### EquivCluster")
    md_lines.append(md_table(
        ["answer_type", "Total", "Correct", "Accuracy"],
        [[r["answer_type"], r["total"], r["correct"], r["accuracy"]] for r in type_equiv_rows]
    ))
    md_lines.append("")

    md_lines.append("## Sample Position Accuracy")
    sample_rows = []
    for pos in sorted(sample_position_total):
        total_pos = sample_position_total[pos]
        parsed_pos = sample_position_parsed[pos]
        correct_pos = sample_position_correct[pos]
        sample_rows.append([
            pos,
            total_pos,
            parsed_pos,
            pct(parsed_pos, total_pos),
            correct_pos,
            pct(correct_pos, total_pos),
        ])
    md_lines.append(md_table(
        ["Sample ID", "Total", "Parsed", "Parse Success", "Correct", "Accuracy"],
        sample_rows
    ))
    md_lines.append("")

    md_lines.append("## Distributions")
    md_lines.append("### Finish reason, sample-level")
    md_lines.append(md_table(
        ["finish_reason", "Count"],
        [[repr(k), v] for k, v in finish_counter.items()]
    ))
    md_lines.append("")
    md_lines.append("### raw_unique_count")
    md_lines.append(md_table(
        ["raw_unique_count", "Count"],
        [[k, v] for k, v in sorted(raw_unique_counter.items(), key=lambda x: x[0])]
    ))
    md_lines.append("")
    md_lines.append("### equiv_cluster_count")
    md_lines.append(md_table(
        ["equiv_cluster_count", "Count"],
        [[k, v] for k, v in sorted(equiv_cluster_counter.items(), key=lambda x: x[0])]
    ))
    md_lines.append("")

    md_lines.append("## Token Usage")
    token_rows = [
        ["Total sample calls", total_sample_calls],
        ["Total prompt tokens", total_prompt_tokens],
        ["Total completion tokens", total_completion_tokens],
        ["Total tokens", total_tokens],
        ["Avg prompt tokens / call", f"{summary['token_usage']['avg_prompt_tokens_per_call']:.2f}" if summary["token_usage"]["avg_prompt_tokens_per_call"] is not None else "N/A"],
        ["Avg completion tokens / call", f"{summary['token_usage']['avg_completion_tokens_per_call']:.2f}" if summary["token_usage"]["avg_completion_tokens_per_call"] is not None else "N/A"],
        ["Avg total tokens / call", f"{summary['token_usage']['avg_total_tokens_per_call']:.2f}" if summary["token_usage"]["avg_total_tokens_per_call"] is not None else "N/A"],
    ]
    md_lines.append(md_table(["Metric", "Value"], token_rows))
    md_lines.append("")

    md_lines.append("## Important Case Lists")
    case_groups = [
        ("RawVote wrong but Oracle@3 correct", "raw_vote_missed_oracle"),
        ("EquivCluster correct while RawVote wrong", "equiv_recovers_raw"),
        ("SC3 recovers Single-CoT failure", "sc3_recovers_single"),
        ("SC3 regresses from Single-CoT success", "sc3_regresses_single"),
        ("Raw disagreement but one equivalent cluster", "raw_disagree_but_one_equiv_cluster"),
        ("Unanimous but wrong", "unanimous_wrong"),
        ("Majority wrong", "majority_wrong"),
    ]

    for title, key in case_groups:
        selected = [c for c in cases if c.get(key) is True]
        md_lines.append(f"### {title}")
        md_lines.append(f"Count: **{len(selected)}**")
        if selected:
            rows = []
            for c in selected[:20]:
                rows.append([
                    c["id"],
                    c["question_id"],
                    c["answer_type"],
                    c["raw_selected_support"],
                    c["equiv_selected_support"],
                    short_text(c["gold"], 80),
                    short_text(c["raw_selected_answer"], 80),
                    short_text(c["equiv_selected_answer"], 80),
                    short_text(c["pred_answers"], 120),
                ])
            md_lines.append(md_table(
                ["id", "qid", "type", "raw_sup", "eq_sup", "gold", "raw_selected", "eq_selected", "pred_answers"],
                rows
            ))
        md_lines.append("")

    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    print("\n=== AMO-P SC3 Analysis Summary ===")
    print("Total:", total)

    if single_available:
        print("Single-CoT:", f"{single_correct}/{len(single_eval_cases)}", pct(single_correct, len(single_eval_cases)))

    print("SC3-RawVote:", f"{global_counter['raw_correct']}/{total}", pct(global_counter["raw_correct"], total))
    print("Oracle@3:", f"{global_counter['oracle_correct']}/{total}", pct(global_counter["oracle_correct"], total))
    print("SC3-EquivCluster:", f"{global_counter['equiv_correct']}/{total}", pct(global_counter["equiv_correct"], total))

    print("\nRaw disagreement:", global_counter["raw_disagreement"], pct(global_counter["raw_disagreement"], total))
    print("Equiv disagreement:", global_counter["equiv_disagreement"], pct(global_counter["equiv_disagreement"], total))
    print("RawVote wrong but Oracle@3 correct:", global_counter["raw_vote_missed_oracle"])
    print("EquivCluster correct while RawVote wrong:", global_counter["equiv_recovers_raw"])
    print("No majority support<=1:", global_counter["no_majority"])
    print("Majority wrong support>=2:", global_counter["majority_wrong"])

    if single_available:
        print("\nSC3 recovers Single-CoT failure:", global_counter["sc3_recovers_single"])
        print("SC3 regresses from Single-CoT success:", global_counter["sc3_regresses_single"])
        print("Oracle@3 recovers Single-CoT failure:", global_counter["oracle_recovers_single"])

    print("\nSaved:")
    print("-", OUT_MD)
    print("-", OUT_JSON)
    print("-", OUT_CASES_JSONL)
    print("-", OUT_CASES_CSV)


if __name__ == "__main__":
    main()
