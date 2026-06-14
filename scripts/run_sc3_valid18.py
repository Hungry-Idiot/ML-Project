import json
from pathlib import Path
from collections import Counter

from datasets import load_dataset

from scripts.run_single_20_v2 import (
    get_client,
    call_llm,
    extract_boxed,
    safe_verify,
)

OUT_PATH = Path("outputs/sc3_valid18.jsonl")
VALID_IDS_PATH = Path("outputs/valid_ids_20.txt")


def choose_majority(answers):
    """
    简单 Self-Consistency:
    - 去掉 None
    - 选出现次数最多的答案
    - 如果都只出现一次，就选第一个非空答案
    """
    valid_answers = [a for a in answers if a is not None]

    if not valid_answers:
        return None

    counter = Counter(valid_answers)
    return counter.most_common(1)[0][0]


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )

    valid_ids = [
        int(x.strip())
        for x in VALID_IDS_PATH.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]

    # 先只跑 5 题
    test_ids = valid_ids

    client = get_client()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = len(test_ids)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for idx in test_ids:
            ex = ds[idx]
            problem = ex["problem"]
            gold = ex["answer"]

            print(f"\n===== Problem {idx} =====")

            raw_outputs = []
            pred_answers = []

            for sample_id in range(3):
                print(f"sample {sample_id + 1}/3")
                raw = call_llm(client, problem)
                pred = extract_boxed(raw)

                raw_outputs.append(raw)
                pred_answers.append(pred)

                print("pred:", pred)

            selected_answer = choose_majority(pred_answers)
            is_correct = safe_verify(gold, selected_answer)
            correct += int(is_correct)

            record = {
                "id": idx,
                "problem": problem,
                "gold": gold,
                "raw_outputs": raw_outputs,
                "pred_answers": pred_answers,
                "selected_answer": selected_answer,
                "pred_answer": selected_answer,
                "correct": is_correct,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print("gold:", gold)
            print("selected_answer:", selected_answer)
            print("correct:", is_correct)

    print(f"\nSaved to {OUT_PATH}")
    print(f"Accuracy: {correct}/{total} = {correct / total:.2%}")


if __name__ == "__main__":
    main()