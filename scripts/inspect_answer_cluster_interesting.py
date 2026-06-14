import json
from pathlib import Path

IN_PATH = Path("outputs/answer_cluster_valid47.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        agent_answers = [a for a in ex.get("agent_answers", []) if a is not None]
        raw_unique = set(agent_answers)
        clusters = ex.get("answer_clusters", [])

        raw_disagree_but_one_cluster = (
            len(raw_unique) > 1 and len(clusters) == 1
        )

        support_not_3 = (
            len(clusters) == 1 and clusters[0].get("support_count") != 3
        )

        if raw_disagree_but_one_cluster or support_not_3:
            print("\n==============================")
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("agent_answers:", ex["agent_answers"])
            print("answer_clusters:", ex["answer_clusters"])
            print("selected_answer:", ex["selected_answer"])
            print("correct:", ex["correct"])

            if raw_disagree_but_one_cluster:
                print("case_type: raw disagreement but equivalent cluster")

            if support_not_3:
                print("case_type: support_count is not 3")

            print("\n--- agent outputs tail ---")
            for i, raw in enumerate(ex["agent_outputs"]):
                print(f"\nAgent {i + 1}:")
                print((raw or "")[-500:])