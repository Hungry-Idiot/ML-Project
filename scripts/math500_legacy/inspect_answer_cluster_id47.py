import json
from pathlib import Path

IN_PATH = Path("outputs/answer_cluster_valid47.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        if ex["id"] == 47:
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("agent_answers:", ex["agent_answers"])
            print("answer_clusters:", ex["answer_clusters"])
            print("selected_answer:", ex["selected_answer"])
            print("correct:", ex["correct"])

            print("\n--- agent outputs tail ---")
            for i, raw in enumerate(ex["agent_outputs"]):
                print(f"\nAgent {i + 1}:")
                print((raw or "")[-500:])