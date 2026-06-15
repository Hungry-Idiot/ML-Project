import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from datasets import load_dataset

from scripts.run_single_20_v2 import (
    get_client,
    extract_boxed,
    safe_verify,
)

load_dotenv()

IN_PATH = Path("outputs/naive_delm_valid18.jsonl")
OUT_PATH = Path("outputs/naive_delm_valid18_fixed.jsonl")


def call_short(client, prompt: str) -> str:
    model = os.getenv("MODEL_NAME")

    for attempt in range(3):
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4096,
        )

        content = resp.choices[0].message.content or ""
        finish_reason = resp.choices[0].finish_reason

        if content.strip():
            return content

        print(f"[WARN] empty output retry {attempt + 1}/3, finish_reason={finish_reason}")
        time.sleep(1)

    return ""


def rerun_one(client, problem: str):
    prompt1 = f"""
Solve the problem internally. Do not show reasoning.

Return only:
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    agent1_output = call_short(client, prompt1)
    agent1_answer = extract_boxed(agent1_output)

    prompt2 = f"""
A previous agent gave this answer:
{agent1_answer}

Solve the same problem internally. You may use or reject the previous answer.
Do not show reasoning.

Return only:
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    agent2_output = call_short(client, prompt2)
    agent2_answer = extract_boxed(agent2_output)

    return agent1_output, agent1_answer, agent2_output, agent2_answer


def main():
    ds = load_dataset(
        "json",
        data_files="data/MATH-500/test.jsonl",
        split="train"
    )

    client = get_client()

    fixed = []

    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            ex = json.loads(line)

            if ex.get("pred_answer") is None:
                idx = ex["id"]
                print(f"\nRerunning failed problem id={idx}")

                problem = ds[idx]["problem"]
                gold = ds[idx]["answer"]

                agent1_output, agent1_answer, agent2_output, agent2_answer = rerun_one(
                    client, problem
                )

                selected_answer = agent2_answer
                is_correct = safe_verify(gold, selected_answer)

                ex["agent1_output"] = agent1_output
                ex["agent1_answer"] = agent1_answer
                ex["agent2_output"] = agent2_output
                ex["agent2_answer"] = agent2_answer
                ex["selected_answer"] = selected_answer
                ex["pred_answer"] = selected_answer
                ex["correct"] = is_correct
                ex["rerun_fixed"] = True

                print("gold:", gold)
                print("agent1_answer:", agent1_answer)
                print("agent2_answer:", agent2_answer)
                print("correct:", is_correct)

            fixed.append(ex)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for ex in fixed:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print("\nSaved to", OUT_PATH)


if __name__ == "__main__":
    main()