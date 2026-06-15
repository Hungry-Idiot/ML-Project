import csv
import json
from pathlib import Path


OUTPUT_DIR = Path("outputs")

SUMMARY_MD_PATH = OUTPUT_DIR / "current_results_summary.md"
SUMMARY_CSV_PATH = OUTPUT_DIR / "current_results_summary.csv"


def read_jsonl(path: Path):
    """Read a jsonl file. If the file does not exist, return None."""
    if not path.exists():
        return None

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_valid_ids(path: Path):
    """Read valid id list. If the file does not exist, return None."""
    if not path.exists():
        return None

    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.append(int(line))
    return set(ids)


def pct(num, den):
    if den == 0:
        return "N/A"
    return f"{num / den * 100:.2f}%"


def summarize_basic(name: str, records):
    """Summarize common metrics for one experiment."""
    if records is None:
        return {
            "Method": name,
            "Total": "MISSING",
            "Correct": "MISSING",
            "Accuracy": "MISSING",
            "Parse Fail": "MISSING",
            "Parse Success": "MISSING",
        }

    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in records if ex.get("pred_answer") is None)

    return {
        "Method": name,
        "Total": total,
        "Correct": correct,
        "Accuracy": pct(correct, total),
        "Parse Fail": parse_fail,
        "Parse Success": pct(total - parse_fail, total),
    }


def summarize_answer_cluster(records):
    """Extra statistics for Answer-Cluster-DeLM."""
    if records is None:
        return None

    total = len(records)
    one_cluster = 0
    multi_cluster = 0
    support_3 = 0
    raw_disagree_but_one_cluster = 0
    support_not_3 = 0

    for ex in records:
        clusters = ex.get("answer_clusters", [])
        agent_answers = [a for a in ex.get("agent_answers", []) if a is not None]
        raw_unique = set(agent_answers)

        if len(clusters) == 1:
            one_cluster += 1

            if clusters[0].get("support_count") == 3:
                support_3 += 1
            else:
                support_not_3 += 1

            if len(raw_unique) > 1:
                raw_disagree_but_one_cluster += 1

        if len(clusters) > 1:
            multi_cluster += 1

    return {
        "Total": total,
        "One-cluster problems": one_cluster,
        "Multi-cluster problems": multi_cluster,
        "Problems with support_count=3": support_3,
        "Raw disagreement but one equivalent cluster": raw_disagree_but_one_cluster,
        "Problems with support_count not 3": support_not_3,
    }


def make_markdown_table(rows):
    headers = [
        "Method",
        "Total",
        "Correct",
        "Accuracy",
        "Parse Fail",
        "Parse Success",
    ]

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        lines.append(
            "| "
            + " | ".join(str(row.get(h, "")) for h in headers)
            + " |"
        )

    return "\n".join(lines)


def write_csv(rows, path: Path):
    headers = [
        "Method",
        "Total",
        "Correct",
        "Accuracy",
        "Parse Fail",
        "Parse Success",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    single_50 = read_jsonl(OUTPUT_DIR / "single_50.jsonl")
    valid_ids_50 = read_valid_ids(OUTPUT_DIR / "valid_ids_50.txt")

    if single_50 is not None and valid_ids_50 is not None:
        single_50_valid47 = [
            ex for ex in single_50
            if ex.get("id") in valid_ids_50
        ]
    else:
        single_50_valid47 = None

    sc3_valid47 = read_jsonl(OUTPUT_DIR / "sc3_valid47.jsonl")
    answer_cluster_valid47 = read_jsonl(OUTPUT_DIR / "answer_cluster_valid47.jsonl")
    naive_delm_valid18_fixed = read_jsonl(OUTPUT_DIR / "naive_delm_valid18_fixed.jsonl")

    rows = [
        summarize_basic("Single-CoT full50", single_50),
        summarize_basic("Single-CoT valid47", single_50_valid47),
        summarize_basic("Self-Consistency-3 valid47", sc3_valid47),
        summarize_basic("Answer-Cluster-DeLM valid47", answer_cluster_valid47),
        summarize_basic("Naive-DeLM fixed valid18", naive_delm_valid18_fixed),
    ]

    print("\n=== Main Results ===")
    print(make_markdown_table(rows))

    answer_cluster_extra = summarize_answer_cluster(answer_cluster_valid47)

    md_parts = []
    md_parts.append("# Current Experiment Results Summary\n")
    md_parts.append("## Main Results\n")
    md_parts.append(make_markdown_table(rows))
    md_parts.append("\n")

    if answer_cluster_extra is not None:
        md_parts.append("## Answer-Cluster-DeLM Extra Statistics\n")
        for k, v in answer_cluster_extra.items():
            md_parts.append(f"- {k}: {v}")
        md_parts.append("\n")

        print("\n=== Answer-Cluster-DeLM Extra Statistics ===")
        for k, v in answer_cluster_extra.items():
            print(f"{k}: {v}")

    md_parts.append("## Notes\n")
    md_parts.append(
        "- `Single-CoT full50` includes parse failures from the original 50 examples."
    )
    md_parts.append(
        "- `Single-CoT valid47` filters `single_50.jsonl` by `valid_ids_50.txt`; it removes parse-fail examples but keeps real wrong answers."
    )
    md_parts.append(
        "- `Self-Consistency-3 valid47` and `Answer-Cluster-DeLM valid47` are compared on the same valid47 subset."
    )
    md_parts.append(
        "- `Naive-DeLM fixed valid18` is kept as a smaller auxiliary baseline."
    )

    SUMMARY_MD_PATH.write_text("\n".join(md_parts), encoding="utf-8")
    write_csv(rows, SUMMARY_CSV_PATH)

    print(f"\nSaved markdown summary to: {SUMMARY_MD_PATH}")
    print(f"Saved csv summary to: {SUMMARY_CSV_PATH}")


if __name__ == "__main__":
    main()