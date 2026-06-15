import os
import sys
import json
import time
from pathlib import Path

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

IN_PATH = Path("outputs/single_level5.jsonl")
OUT_PATH = Path("outputs/single_level5_fixed.jsonl")
VALID_IDS_PATH = Path("outputs/valid_ids_level5.txt")

MAX_TOKENS = int(os.getenv("RERUN_MAX_TOKENS", "8192"))
RETRY = 4


def call_final_answer_only(client, problem: str) -> str:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    prompt = f"""
You are solving a math competition problem.

Important:
- Do NOT show reasoning.
- Do NOT explain.
- Output only the final answer.
- The answer must be in exactly this format:

Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    last_content = ""

    for attempt in range(RETRY):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
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
            last_content = content

        except Exception as e:
            print(f"[WARN] API error, retry {attempt + 1}/{RETRY}: {repr(e)}")

        time.sleep(1)

    return last_content


def read_jsonl(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(
            f"Input file not found: {IN_PATH}\n"
            "Please run scripts/run_single_level5.py first."
        )

    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train",
    )

    client = get_client()
    records = read_jsonl(IN_PATH)

    parse_fail_records = [
        ex for ex in records
        if ex.get("pred_answer") is None
    ]

    print("Input file:", IN_PATH)
    print("Total records:", len(records))
    print("Parse fail records to rerun:", len(parse_fail_records))
    print("Max tokens:", MAX_TOKENS)

    fixed_records = []

    for ex in records:
        if ex.get("pred_answer") is not None:
            fixed_records.append(ex)
            continue

        idx = ex["id"]
        problem = ds[idx]["problem"]
        gold = ds[idx]["answer"]

        print(f"\n===== Rerun parse-fail problem id={idx} =====")

        old_raw_output = ex.get("raw_output")
        old_pred_answer = ex.get("pred_answer")

        raw_output = call_final_answer_only(client, problem)
        pred_answer = extract_boxed(raw_output)
        is_correct = safe_verify(gold, pred_answer)

        new_ex = dict(ex)
        new_ex["old_raw_output"] = old_raw_output
        new_ex["old_pred_answer"] = old_pred_answer
        new_ex["raw_output"] = raw_output
        new_ex["pred_answer"] = pred_answer
        new_ex["correct"] = is_correct
        new_ex["rerun_fixed"] = True

        fixed_records.append(new_ex)

        print("gold:", gold)
        print("pred_answer:", pred_answer)
        print("correct:", is_correct)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for ex in fixed_records:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    valid_ids = [
        ex["id"]
        for ex in fixed_records
        if ex.get("pred_answer") is not None
    ]

    with VALID_IDS_PATH.open("w", encoding="utf-8") as f:
        for idx in valid_ids:
            f.write(str(idx) + "\n")

    total = len(fixed_records)
    correct = sum(1 for ex in fixed_records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in fixed_records if ex.get("pred_answer") is None)

    print("\nSaved fixed results to:", OUT_PATH)
    print("Saved valid ids to:", VALID_IDS_PATH)

    print("\n=== Fixed Single-CoT Level5 Results ===")
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
    print("Parse fail:", parse_fail)
    print("Parse success:", f"{(total - parse_fail) / total:.2%}" if total else "N/A")
    print("Valid id count:", len(valid_ids))


if __name__ == "__main__":
    main()