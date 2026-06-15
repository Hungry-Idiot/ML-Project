import sys
import json
from pathlib import Path

from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_single_20_v2 import (
    get_client,
    call_llm,
    extract_boxed,
    safe_verify,
)


IDS_PATH = Path("outputs/hard_ids_level5.txt")
OUT_PATH = Path("outputs/single_level5.jsonl")


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )

    level5_ids = [
        int(x.strip())
        for x in IDS_PATH.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]

    client = get_client()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = len(level5_ids)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for n, idx in enumerate(level5_ids, start=1):
            ex = ds[idx]
            problem = ex["problem"]
            gold = ex["answer"]
            level = ex.get("level")
            problem_type = ex.get("type")

            print(f"\n===== Level5 Problem {n}/{total}, id={idx} =====")

            raw_output = call_llm(client, problem)
            pred_answer = extract_boxed(raw_output)
            is_correct = safe_verify(gold, pred_answer)

            correct += int(is_correct)

            record = {
                "id": idx,
                "level": level,
                "type": problem_type,
                "problem": problem,
                "gold": gold,
                "raw_output": raw_output,
                "pred_answer": pred_answer,
                "correct": is_correct,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print("gold:", gold)
            print("pred_answer:", pred_answer)
            print("correct:", is_correct)

    print(f"\nSaved to {OUT_PATH}")
    print(f"Total: {total}")
    print(f"Correct: {correct}")
    print(f"Accuracy: {correct / total:.2%}")


if __name__ == "__main__":
    main()