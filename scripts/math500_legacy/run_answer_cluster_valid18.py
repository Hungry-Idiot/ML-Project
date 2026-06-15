import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
from datasets import load_dataset
from math_verify import parse, verify

from scripts.run_single_20_v2 import (
    get_client,
    extract_boxed,
    safe_verify,
)

load_dotenv()

OUT_PATH = Path("outputs/answer_cluster_valid18.jsonl")
VALID_IDS_PATH = Path("outputs/valid_ids_20.txt")


def equivalent(ans1: str | None, ans2: str | None) -> bool:
    if ans1 is None or ans2 is None:
        return False

    candidates1 = [
        ans1,
        f"\\boxed{{{ans1}}}",
        f"Final Answer: \\boxed{{{ans1}}}",
    ]

    candidates2 = [
        ans2,
        f"\\boxed{{{ans2}}}",
        f"Final Answer: \\boxed{{{ans2}}}",
    ]

    for a in candidates1:
        for b in candidates2:
            try:
                if verify(parse(a), parse(b)):
                    return True
            except Exception:
                pass

    return False


def add_to_clusters(clusters, answer, agent_name, raw_output):
    if answer is None:
        return clusters

    for cluster in clusters:
        if equivalent(answer, cluster["canonical_answer"]):
            cluster["members"].append({
                "agent": agent_name,
                "answer": answer,
            })
            cluster["support_count"] += 1
            return clusters

    clusters.append({
        "canonical_answer": answer,
        "members": [
            {
                "agent": agent_name,
                "answer": answer,
            }
        ],
        "support_count": 1,
    })

    return clusters


def clusters_to_text(clusters):
    if not clusters:
        return "No previous answer clusters."

    lines = []
    for i, c in enumerate(clusters):
        lines.append(
            f"Cluster {i}: answer = {c['canonical_answer']}, support = {c['support_count']}"
        )
    return "\n".join(lines)


def call_agent(client, problem: str, clusters, agent_name: str) -> str:
    model = os.getenv("MODEL_NAME")

    if agent_name == "agent1":
        prompt = f"""
Solve the problem internally. Do not show long reasoning.

Return exactly two lines:
Check: one short sentence
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""
    else:
        cluster_text = clusters_to_text(clusters)
        prompt = f"""
You are a math solver in a DeLM-style multi-agent system.

Current shared answer clusters:
{cluster_text}

Solve the same problem internally.
You may confirm an existing cluster or propose a different answer.
Do not copy blindly.
Do not show long reasoning.

Return exactly two lines:
Check: one short sentence
Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

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

        print(f"[WARN] {agent_name} empty output retry {attempt + 1}/3, finish_reason={finish_reason}")
        time.sleep(1)

    return ""


def choose_from_clusters(clusters):
    if not clusters:
        return None

    clusters = sorted(clusters, key=lambda x: x["support_count"], reverse=True)
    return clusters[0]["canonical_answer"]


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

    test_ids = valid_ids
    client = get_client()

    correct = 0
    total = len(test_ids)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for idx in test_ids:
            ex = ds[idx]
            problem = ex["problem"]
            gold = ex["answer"]

            print(f"\n===== Problem {idx} =====")

            clusters = []
            agent_outputs = []
            agent_answers = []

            for agent_name in ["agent1", "agent2", "agent3"]:
                raw_output = call_agent(client, problem, clusters, agent_name)
                answer = extract_boxed(raw_output)

                clusters = add_to_clusters(
                    clusters=clusters,
                    answer=answer,
                    agent_name=agent_name,
                    raw_output=raw_output,
                )

                agent_outputs.append(raw_output)
                agent_answers.append(answer)

                print(agent_name, "answer:", answer)
                print("clusters:", clusters_to_text(clusters))

            selected_answer = choose_from_clusters(clusters)
            is_correct = safe_verify(gold, selected_answer)
            correct += int(is_correct)

            record = {
                "id": idx,
                "problem": problem,
                "gold": gold,
                "agent_outputs": agent_outputs,
                "agent_answers": agent_answers,
                "answer_clusters": clusters,
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