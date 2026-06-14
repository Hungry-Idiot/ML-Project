import os
import json
from pathlib import Path
from datasets import load_dataset
from dotenv import load_dotenv
from openai import OpenAI
from math_verify import parse, verify

load_dotenv()

OUT_PATH = Path("outputs/single_3.jsonl")


def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("Please set OPENAI_API_KEY in .env")

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def call_llm(client, problem: str) -> str:
    model = os.getenv("MODEL_NAME", "gpt-4o-mini")

    prompt = f"""
Solve the following math problem.

You must give the final answer in this format:
Final Answer: \\boxed{{...}}

Problem:
{problem}
"""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1024,
    )

    return resp.choices[0].message.content


def safe_verify(gold: str, pred_text: str) -> bool:
    try:
        gold_parsed = parse(gold)
        pred_parsed = parse(pred_text)
        return bool(verify(gold_parsed, pred_parsed))
    except Exception as e:
        print("Verify error:", repr(e))
        return False


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )
    client = get_client()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = 3

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for i in range(total):
            ex = ds[i]
            problem = ex["problem"]
            gold = ex["answer"]

            print(f"\nRunning problem {i}...")
            raw_output = call_llm(client, problem)
            is_correct = safe_verify(gold, raw_output)
            correct += int(is_correct)

            record = {
                "id": i,
                "problem": problem,
                "gold": gold,
                "raw_output": raw_output,
                "correct": is_correct,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print("Gold:", gold)
            print("Correct:", is_correct)

    print(f"\nSaved to {OUT_PATH}")
    print(f"Accuracy: {correct}/{total} = {correct / total:.2%}")


if __name__ == "__main__":
    main()