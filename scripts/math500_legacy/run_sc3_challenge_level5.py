import os
import sys
import json
import time
from pathlib import Path
from collections import Counter

from dotenv import load_dotenv
from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_single_20_v2 import (
    get_client,
    extract_boxed,
    safe_verify,
)


load_dotenv()

IDS_PATH = Path("outputs/challenge_ids_level5_wrong.txt")
OUT_PATH = Path("outputs/sc3_challenge_level5.jsonl")

MAX_TOKENS = int(os.getenv("SC3_MAX_TOKENS", "8192"))
RETRY = 1


def call_llm_final_only(client, problem: str) -> str:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    prompt = f"""
You are solving a hard math competition problem.

Important:
- Do NOT show reasoning.
- Do NOT explain.
- Output only the final answer.
- The answer must be in exactly this format:

Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    for attempt in range(RETRY):
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=MAX_TOKENS,
        )

        content = resp.choices[0].message.content or ""
        finish_reason = resp.choices[0].finish_reason

        if content.strip():
            return content

        print(
            f"[WARN] empty output, retry {attempt + 1}/{RETRY}, "
            f"finish_reason={finish_reason}"
        )

        # 关键：如果是 length，说明这次已经浪费了大量 token。
        # 不要继续 retry，直接返回空结果。
        if finish_reason == "length":
            return ""

        time.sleep(1)

    return ""


def choose_majority(answers):
    valid_answers = [a for a in answers if a is not None]

    if not valid_answers:
        return None

    counter = Counter(valid_answers)
    return counter.most_common(1)[0][0]


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train",
    )

    challenge_ids = [
        int(x.strip())
        for x in IDS_PATH.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]

    client = get_client()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = len(challenge_ids)
    parse_fail = 0

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for n, idx in enumerate(challenge_ids, start=1):
            ex = ds[idx]
            problem = ex["problem"]
            gold = ex["answer"]

            print(f"\n===== SC3 Challenge Problem {n}/{total}, id={idx} =====")

            raw_outputs = []
            pred_answers = []

            for sample_id in range(3):
                print(f"sample {sample_id + 1}/3")

                raw = call_llm_final_only(client, problem)
                pred = extract_boxed(raw)

                raw_outputs.append(raw)
                pred_answers.append(pred)

                print("pred:", pred)

            selected_answer = choose_majority(pred_answers)
            is_correct = safe_verify(gold, selected_answer)

            correct += int(is_correct)

            if selected_answer is None:
                parse_fail += 1

            record = {
                "id": idx,
                "level": ex.get("level"),
                "type": ex.get("type"),
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
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
    print("Parse fail:", parse_fail)
    print("Parse success:", f"{(total - parse_fail) / total:.2%}" if total else "N/A")


if __name__ == "__main__":
    main()