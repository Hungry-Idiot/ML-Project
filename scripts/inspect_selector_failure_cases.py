import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ANALYSIS_CASES_PATH = Path("outputs/amo_parser_sc3_analysis_cases.jsonl")
SC3_PATH = Path("outputs/amo_parser_sc3.jsonl")
SELECTOR_PATH = Path("outputs/amo_parser_selector_on_sc3.jsonl")
SINGLE_PATH = Path("outputs/amo_parser_single.jsonl")
DATA_PATH = Path("data/AMO-Bench/test.jsonl")

OUT_MD = Path("outputs/selector_failure_cases.md")
OUT_JSONL = Path("outputs/selector_failure_cases.jsonl")
OUT_CSV = Path("outputs/selector_failure_cases.csv")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    return records


def build_lookup(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    lookup = {}
    for ex in records:
        if "id" in ex:
            lookup[int(ex["id"])] = ex
    return lookup


def short_text(x: Any, max_len: int = 180) -> str:
    if x is None:
        return ""

    s = str(x).replace("\n", " ").strip()

    if len(s) <= max_len:
        return s

    return s[:max_len] + "..."


def tail_text(x: Any, max_len: int = 1200) -> str:
    if x is None:
        return ""

    s = str(x).strip()

    if len(s) <= max_len:
        return s

    return s[-max_len:]


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        clean_row = []
        for item in row:
            text = str(item)
            text = text.replace("\n", "<br>")
            text = text.replace("|", "\\|")
            clean_row.append(text)
        lines.append("| " + " | ".join(clean_row) + " |")

    return "\n".join(lines)


def code_block(text: Any, lang: str = "") -> str:
    text = "" if text is None else str(text)
    fence = "```"
    return f"{fence}{lang}\n{text}\n{fence}"


def get_sc3_pred_answers(sc3_ex: dict[str, Any]) -> list[str | None]:
    if not sc3_ex:
        return []

    if isinstance(sc3_ex.get("pred_answers"), list):
        return sc3_ex["pred_answers"]

    sample_records = sc3_ex.get("sample_records", [])
    if isinstance(sample_records, list):
        return [s.get("pred_answer") for s in sample_records]

    return []


def get_sc3_sample_records(sc3_ex: dict[str, Any]) -> list[dict[str, Any]]:
    if not sc3_ex:
        return []

    sample_records = sc3_ex.get("sample_records", [])
    if isinstance(sample_records, list):
        return sample_records

    return []


def extract_sample_tails_from_sc3(sc3_ex: dict[str, Any], max_len: int = 1200) -> list[str]:
    sample_records = get_sc3_sample_records(sc3_ex)

    tails = []
    for sample in sample_records:
        tails.append(tail_text(sample.get("raw_output"), max_len))

    return tails


def get_selector_choice(selector_ex: dict[str, Any]) -> dict[str, Any]:
    if not selector_ex:
        return {
            "selected_cluster_id": None,
            "selected_answer": None,
            "correct": None,
            "selected_support": None,
            "used_fallback": None,
            "raw_output_tail": "",
        }

    return {
        "selected_cluster_id": selector_ex.get("selected_cluster_id"),
        "selected_answer": selector_ex.get("selected_answer"),
        "correct": selector_ex.get("correct"),
        "selected_support": selector_ex.get("selected_support"),
        "used_fallback": selector_ex.get("used_fallback"),
        "raw_output_tail": tail_text(selector_ex.get("selector_raw_output"), 1200),
    }


def get_correct_sample_ids(case: dict[str, Any]) -> list[int]:
    flags = case.get("sample_correct_flags", [])
    ids = []

    if isinstance(flags, list):
        for i, flag in enumerate(flags):
            if flag is True:
                ids.append(i)

    return ids


def compact_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []

    for c in clusters or []:
        members = []
        for m in c.get("members", []):
            members.append({
                "sample_id": m.get("sample_id"),
                "answer": m.get("answer"),
            })

        out.append({
            "cluster_id": c.get("cluster_id"),
            "canonical_answer": c.get("canonical_answer"),
            "support_count": c.get("support_count"),
            "members": members,
        })

    return out


def main():
    if not ANALYSIS_CASES_PATH.exists():
        raise FileNotFoundError(
            f"Missing {ANALYSIS_CASES_PATH}\n"
            "Please run scripts/analyze_sc3_amo_parser.py first."
        )

    analysis_cases = read_jsonl(ANALYSIS_CASES_PATH)
    sc3_lookup = build_lookup(read_jsonl(SC3_PATH))
    selector_lookup = build_lookup(read_jsonl(SELECTOR_PATH))
    single_lookup = build_lookup(read_jsonl(SINGLE_PATH))
    data_lookup = build_lookup(read_jsonl(DATA_PATH))

    target_cases = [
        c for c in analysis_cases
        if c.get("raw_vote_missed_oracle") is True
    ]

    target_cases.sort(key=lambda x: int(x["id"]))

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    detailed_records = []

    print("\n=== Selector Failure / Oracle Gap Cases ===")
    print("Input analysis cases:", ANALYSIS_CASES_PATH)
    print("SC3 file:", SC3_PATH)
    print("Selector file:", SELECTOR_PATH)
    print("Case condition: raw_vote_missed_oracle == True")
    print("Count:", len(target_cases))

    for case in target_cases:
        idx = int(case["id"])

        sc3_ex = sc3_lookup.get(idx, {})
        selector_ex = selector_lookup.get(idx, {})
        single_ex = single_lookup.get(idx, {})
        data_ex = data_lookup.get(idx, {})

        pred_answers = case.get("pred_answers") or get_sc3_pred_answers(sc3_ex)
        sample_correct_flags = case.get("sample_correct_flags", [])
        correct_sample_ids = get_correct_sample_ids(case)

        sample_output_tails = case.get("sample_output_tails")
        if not sample_output_tails:
            sample_output_tails = extract_sample_tails_from_sc3(sc3_ex)

        selector_choice = get_selector_choice(selector_ex)

        selector_clusters = selector_ex.get("clusters", [])
        if not selector_clusters:
            selector_clusters = case.get("equiv_clusters", [])

        record = {
            "id": idx,
            "question_id": case.get("question_id"),
            "answer_type": case.get("answer_type"),
            "problem": data_ex.get("problem") or case.get("problem") or sc3_ex.get("problem"),
            "gold": case.get("gold"),

            "single_pred_answer": case.get("single_pred_answer") or single_ex.get("pred_answer"),
            "single_correct": case.get("single_correct"),

            "sc3_pred_answers": pred_answers,
            "sample_correct_flags": sample_correct_flags,
            "correct_sample_ids": correct_sample_ids,
            "raw_selected_answer": case.get("raw_selected_answer"),
            "raw_selected_support": case.get("raw_selected_support"),
            "raw_correct": case.get("raw_correct"),

            "oracle_correct": case.get("oracle_correct"),
            "equiv_selected_answer": case.get("equiv_selected_answer"),
            "equiv_selected_support": case.get("equiv_selected_support"),
            "equiv_correct": case.get("equiv_correct"),

            "selector_selected_cluster_id": selector_choice["selected_cluster_id"],
            "selector_selected_answer": selector_choice["selected_answer"],
            "selector_selected_support": selector_choice["selected_support"],
            "selector_correct": selector_choice["correct"],
            "selector_used_fallback": selector_choice["used_fallback"],
            "selector_raw_output_tail": selector_choice["raw_output_tail"],

            "clusters": compact_clusters(selector_clusters),
            "sample_output_tails": sample_output_tails,
        }

        detailed_records.append(record)

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for record in detailed_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "id",
            "question_id",
            "answer_type",
            "gold",
            "single_pred_answer",
            "single_correct",
            "sc3_pred_answers",
            "sample_correct_flags",
            "correct_sample_ids",
            "raw_selected_answer",
            "raw_selected_support",
            "selector_selected_answer",
            "selector_selected_cluster_id",
            "selector_selected_support",
            "selector_correct",
            "selector_used_fallback",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in detailed_records:
            writer.writerow({
                "id": r["id"],
                "question_id": r["question_id"],
                "answer_type": r["answer_type"],
                "gold": short_text(r["gold"], 300),
                "single_pred_answer": short_text(r["single_pred_answer"], 200),
                "single_correct": r["single_correct"],
                "sc3_pred_answers": short_text(r["sc3_pred_answers"], 600),
                "sample_correct_flags": r["sample_correct_flags"],
                "correct_sample_ids": r["correct_sample_ids"],
                "raw_selected_answer": short_text(r["raw_selected_answer"], 200),
                "raw_selected_support": r["raw_selected_support"],
                "selector_selected_answer": short_text(r["selector_selected_answer"], 200),
                "selector_selected_cluster_id": r["selector_selected_cluster_id"],
                "selector_selected_support": r["selector_selected_support"],
                "selector_correct": r["selector_correct"],
                "selector_used_fallback": r["selector_used_fallback"],
            })

    md = []

    md.append("# Selector Failure Cases: RawVote Missed Oracle@3")
    md.append("")
    md.append(f"- Analysis source: `{ANALYSIS_CASES_PATH}`")
    md.append(f"- SC3 source: `{SC3_PATH}`")
    md.append(f"- Selector source: `{SELECTOR_PATH}`")
    md.append(f"- Number of cases: **{len(detailed_records)}**")
    md.append("")
    md.append("These are cases where at least one SC3 sample produced a correct answer, but SC3-RawVote selected a wrong answer.")
    md.append("")

    overview_rows = []
    for r in detailed_records:
        overview_rows.append([
            r["id"],
            r["question_id"],
            r["answer_type"],
            short_text(r["gold"], 80),
            short_text(r["raw_selected_answer"], 80),
            r["raw_selected_support"],
            short_text(r["selector_selected_answer"], 80),
            r["selector_selected_support"],
            r["correct_sample_ids"],
        ])

    md.append("## Overview")
    md.append("")
    md.append(md_table(
        [
            "id",
            "qid",
            "type",
            "gold",
            "RawVote selected",
            "Raw support",
            "Selector selected",
            "Selector support",
            "Correct sample ids",
        ],
        overview_rows,
    ))
    md.append("")

    for r in detailed_records:
        md.append(f"## Case id={r['id']}, question_id={r['question_id']}")
        md.append("")
        md.append(f"- answer_type: `{r['answer_type']}`")
        md.append(f"- single_pred_answer: `{short_text(r['single_pred_answer'], 200)}`")
        md.append(f"- single_correct: `{r['single_correct']}`")
        md.append(f"- raw_selected_answer: `{short_text(r['raw_selected_answer'], 200)}`")
        md.append(f"- raw_selected_support: `{r['raw_selected_support']}`")
        md.append(f"- selector_selected_answer: `{short_text(r['selector_selected_answer'], 200)}`")
        md.append(f"- selector_selected_cluster_id: `{r['selector_selected_cluster_id']}`")
        md.append(f"- selector_selected_support: `{r['selector_selected_support']}`")
        md.append(f"- selector_correct: `{r['selector_correct']}`")
        md.append(f"- correct_sample_ids: `{r['correct_sample_ids']}`")
        md.append("")

        md.append("### Problem")
        md.append("")
        md.append(code_block(r["problem"], "text"))
        md.append("")

        md.append("### Gold answer")
        md.append("")
        md.append(code_block(r["gold"], "text"))
        md.append("")

        md.append("### SC3 candidate answers")
        md.append("")
        rows = []
        for i, ans in enumerate(r["sc3_pred_answers"]):
            flag = None
            if isinstance(r["sample_correct_flags"], list) and i < len(r["sample_correct_flags"]):
                flag = r["sample_correct_flags"][i]

            rows.append([
                i,
                "YES" if flag is True else "NO",
                short_text(ans, 200),
            ])

        md.append(md_table(["sample_id", "correct?", "pred_answer"], rows))
        md.append("")

        md.append("### Candidate clusters")
        md.append("")
        cluster_rows = []
        for c in r["clusters"]:
            cluster_rows.append([
                c.get("cluster_id"),
                c.get("support_count"),
                short_text(c.get("canonical_answer"), 200),
                short_text(c.get("members"), 400),
            ])

        if cluster_rows:
            md.append(md_table(
                ["cluster_id", "support", "canonical_answer", "members"],
                cluster_rows,
            ))
        else:
            md.append("_No clusters found._")
        md.append("")

        md.append("### Selector output tail")
        md.append("")
        md.append(code_block(r["selector_raw_output_tail"], "text"))
        md.append("")

        md.append("### SC3 sample output tails")
        md.append("")
        for i, tail in enumerate(r["sample_output_tails"]):
            is_correct = (
                isinstance(r["sample_correct_flags"], list)
                and i < len(r["sample_correct_flags"])
                and r["sample_correct_flags"][i] is True
            )

            md.append(f"#### Sample {i} tail, correct={is_correct}")
            md.append("")
            md.append(code_block(tail, "text"))
            md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("\n=== Summary ===")
    print("Cases:", len(detailed_records))

    for r in detailed_records:
        print("\n--------------------")
        print(f"id={r['id']}, question_id={r['question_id']}, type={r['answer_type']}")
        print("gold:", short_text(r["gold"], 120))
        print("SC3 candidates:")
        for i, ans in enumerate(r["sc3_pred_answers"]):
            flag = (
                isinstance(r["sample_correct_flags"], list)
                and i < len(r["sample_correct_flags"])
                and r["sample_correct_flags"][i] is True
            )
            print(f"  sample {i}: correct={flag}, answer={short_text(ans, 120)}")
        print("RawVote selected:", short_text(r["raw_selected_answer"], 120))
        print("Selector selected:", short_text(r["selector_selected_answer"], 120))
        print("Correct sample ids:", r["correct_sample_ids"])

    print("\nSaved:")
    print("-", OUT_MD)
    print("-", OUT_JSONL)
    print("-", OUT_CSV)


if __name__ == "__main__":
    main()