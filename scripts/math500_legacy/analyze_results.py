import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/analyze_results.py outputs/single_20.jsonl")
        return

    path = Path(sys.argv[1])

    total = 0
    correct = 0
    parse_fail = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            ex = json.loads(line)
            total += 1

            if ex.get("correct"):
                correct += 1

            if ex.get("pred_answer") is None:
                parse_fail += 1

    print("File:", path)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
    print("Parse fail:", parse_fail)
    print("Parse success:", f"{(total - parse_fail) / total:.2%}" if total else "N/A")


if __name__ == "__main__":
    main()