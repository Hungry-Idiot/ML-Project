import json
from pathlib import Path

IN_PATH = Path("outputs/answer_cluster_valid18.jsonl")

total = 0
correct = 0
one_cluster = 0
multi_cluster = 0
all_support_3 = 0
raw_disagree_but_one_cluster = 0

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)
        total += 1

        if ex.get("correct"):
            correct += 1

        clusters = ex.get("answer_clusters", [])
        agent_answers = [a for a in ex.get("agent_answers", []) if a is not None]
        raw_unique = set(agent_answers)

        if len(clusters) == 1:
            one_cluster += 1

        if len(clusters) > 1:
            multi_cluster += 1

        if len(clusters) == 1 and clusters[0].get("support_count") == 3:
            all_support_3 += 1

        if len(raw_unique) > 1 and len(clusters) == 1:
            raw_disagree_but_one_cluster += 1

print("Total:", total)
print("Correct:", correct)
print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
print("One-cluster problems:", one_cluster)
print("Multi-cluster problems:", multi_cluster)
print("Problems with support_count=3:", all_support_3)
print("Raw disagreement but one equivalent cluster:", raw_disagree_but_one_cluster)