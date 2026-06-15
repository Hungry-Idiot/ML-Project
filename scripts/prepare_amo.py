import json
from pathlib import Path

from datasets import load_dataset


PARQUET_PATH = Path("data/AMO-Bench/test.parquet")
OUT_PATH = Path("data/AMO-Bench/test.jsonl")


def main():
    if not PARQUET_PATH.exists():
        raise FileNotFoundError(f"File not found: {PARQUET_PATH}")

    ds = load_dataset(
        "parquet",
        data_files=str(PARQUET_PATH),
        split="train",
    )

    print(ds)
    print("Number of examples:", len(ds))
    print("Columns:", ds.column_names)

    print("\n=== First Example ===")
    ex0 = ds[0]
    for k, v in ex0.items():
        print(f"\n[{k}]")
        print(v)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for i, ex in enumerate(ds):
            record = {
                "id": i,
                "question_id": ex.get("question_id"),
                "problem": ex.get("prompt"),
                "gold": ex.get("answer"),
                "solution": ex.get("solution"),
                "answer_type": ex.get("answer_type"),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\nSaved to {OUT_PATH}")


if __name__ == "__main__":
    main()