import sys
import json
from pathlib import Path
from collections import Counter


def read_jsonl(path: Path):
    records = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    return records


def pct(x, total):
    if total == 0:
        return "N/A"
    return f"{x / total:.2%}"


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_results.py <path_to_jsonl>")
        sys.exit(1)

    path = Path(sys.argv[1])

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    records = read_jsonl(path)

    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in records if ex.get("pred_answer") is None)
    parse_success = total - parse_fail

    finish_counter = Counter(ex.get("finish_reason") for ex in records)
    type_counter = Counter(ex.get("answer_type") for ex in records)

    print("File:", path)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", pct(correct, total))
    print("Parse fail:", parse_fail)
    print("Parse success:", pct(parse_success, total))

    print("\n=== finish_reason distribution ===")
    for k, v in finish_counter.items():
        print(f"{repr(k)}: {v}")

    print("\n=== answer_type distribution ===")
    for k, v in type_counter.items():
        print(f"{repr(k)}: {v}")

    wrong = [
        ex for ex in records
        if ex.get("pred_answer") is not None and ex.get("correct") is not True
    ]

    failed = [
        ex for ex in records
        if ex.get("pred_answer") is None
    ]

    print("\n=== Wrong but parsed ===")
    print("Count:", len(wrong))
    for ex in wrong[:20]:
        print(
            f"id={ex.get('id')}, "
            f"question_id={ex.get('question_id')}, "
            f"type={ex.get('answer_type')}, "
            f"gold={ex.get('gold')}, "
            f"pred={ex.get('pred_answer')}"
        )

    print("\n=== Parse failed ===")
    print("Count:", len(failed))
    for ex in failed[:20]:
        print(
            f"id={ex.get('id')}, "
            f"question_id={ex.get('question_id')}, "
            f"type={ex.get('answer_type')}, "
            f"finish_reason={ex.get('finish_reason')}"
        )


if __name__ == "__main__":
    main()