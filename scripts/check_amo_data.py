import json
from pathlib import Path
from collections import Counter


DATA_PATH = Path("data/AMO-Bench/test.jsonl")


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"File not found: {DATA_PATH}")

    records = []

    with DATA_PATH.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue

            ex = json.loads(line)
            records.append(ex)

    print("File:", DATA_PATH)
    print("Total:", len(records))

    print("\nColumns:")
    print(list(records[0].keys()))

    counter = Counter(str(ex.get("answer_type")) for ex in records)

    print("\n=== answer_type distribution ===")
    for k, v in counter.items():
        print(repr(k), ":", v)

    print("\n=== First 5 examples ===")
    for ex in records[:5]:
        print("\n--------------------")
        print("question_id:", ex.get("question_id"))
        print("answer_type:", ex.get("answer_type"))
        print("answer:", ex.get("answer"))
        print("prompt head:", str(ex.get("prompt"))[:300].replace("\n", " "))


if __name__ == "__main__":
    main()