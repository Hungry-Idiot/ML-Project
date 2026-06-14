import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from datasets import load_dataset
from openai import OpenAI

from scripts.run_single_20_v2 import (
    get_client,
    extract_boxed,
    safe_verify,
)

load_dotenv()

OUT_PATH = Path("outputs/naive_delm_5.jsonl")
VALID_IDS_PATH = Path("outputs/valid_ids_20.txt")


def call_agent1(client, problem: str) -> str:
    model = os.getenv("MODEL_NAME")
    prompt = f"""
Solve the following math problem.

Show only a brief solution, no more than 5 lines.
End with exactly:
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    for attempt in range(3):
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048,
        )
        content = resp.choices[0].message.content or ""
        if content.strip():
            return content
        print(f"[WARN] agent1 empty output retry {attempt + 1}/3, finish_reason={resp.choices[0].finish_reason}")
        time.sleep(1)

    return ""


def call_agent2(client, problem: str, previous_solution: str) -> str:
    model = os.getenv("MODEL_NAME")
    prompt = f"""
You are the second solver.

A previous agent solved the problem as follows:

{previous_solution}

Now solve the same problem again.
You may use or reject the previous solution.
Show only a brief solution, no more than 5 lines.
End with exactly:
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    for attempt in range(3):
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048,
        )
        content = resp.choices[0].message.content or ""
        if content.strip():
            return content
        print(f"[WARN] agent2 empty output retry {attempt + 1}/3, finish_reason={resp.choices[0].finish_reason}")
        time.sleep(1)

    return ""


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

    test_ids = valid_ids[:5]

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

            agent1_output = call_agent1(client, problem)
            agent1_answer = extract_boxed(agent1_output)

            agent2_output = call_agent2(client, problem, agent1_output)
            agent2_answer = extract_boxed(agent2_output)

            # Naive-DeLM: 直接采用第二个 agent 的答案
            selected_answer = agent2_answer
            is_correct = safe_verify(gold, selected_answer)
            correct += int(is_correct)

            record = {
                "id": idx,
                "problem": problem,
                "gold": gold,
                "agent1_output": agent1_output,
                "agent1_answer": agent1_answer,
                "agent2_output": agent2_output,
                "agent2_answer": agent2_answer,
                "selected_answer": selected_answer,
                "pred_answer": selected_answer,
                "correct": is_correct,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print("agent1_answer:", agent1_answer)
            print("agent2_answer:", agent2_answer)
            print("gold:", gold)
            print("correct:", is_correct)

    print(f"\nSaved to {OUT_PATH}")
    print(f"Accuracy: {correct}/{total} = {correct / total:.2%}")


if __name__ == "__main__":
    main()