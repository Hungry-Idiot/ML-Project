import os
import json
from pathlib import Path

from dotenv import load_dotenv
from datasets import load_dataset
from openai import OpenAI
from math_verify import parse, verify

load_dotenv()

OUT_PATH = Path("outputs/single_20.jsonl")


def extract_boxed(text: str) -> str | None:
    key = "\\boxed{"
    start = text.rfind(key)
    if start == -1:
        return None

    i = start + len(key)
    depth = 1
    ans_chars = []

    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            ans_chars.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(ans_chars).strip()
            ans_chars.append(ch)
        else:
            ans_chars.append(ch)
        i += 1

    return None


def safe_verify(gold: str, pred_answer: str | None) -> bool:
    if pred_answer is None:
        return False

    gold_candidates = [
        gold,
        f"\\boxed{{{gold}}}",
        f"Final Answer: \\boxed{{{gold}}}",
    ]

    pred_candidates = [
        pred_answer,
        f"\\boxed{{{pred_answer}}}",
        f"Final Answer: \\boxed{{{pred_answer}}}",
    ]

    for g in gold_candidates:
        for p in pred_candidates:
            try:
                if verify(parse(g), parse(p)):
                    return True
            except Exception:
                pass

    return False


def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing in .env")

    return OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None
    )


def call_llm(client, problem: str) -> str:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    prompt = f"""
Solve the following math problem.

You must end your response with:
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


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )

    client = get_client()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    correct = 0
    total = 20

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for i in range(total):
            ex = ds[i]
            problem = ex["problem"]
            gold = ex["answer"]

            print(f"\n===== Problem {i} =====")

            raw_output = call_llm(client, problem)
            pred_answer = extract_boxed(raw_output)
            is_correct = safe_verify(gold, pred_answer)

            correct += int(is_correct)

            record = {
                "id": i,
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
    print(f"Accuracy: {correct}/{total} = {correct / total:.2%}")


if __name__ == "__main__":
    main()