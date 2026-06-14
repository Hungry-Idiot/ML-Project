import json
from pathlib import Path

IN_PATH = Path("outputs/sc3_clusters_valid18.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        if ex["num_raw_unique_answers"] > 1 and ex["num_equiv_clusters"] == 1:
            print("\n==============================")
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("pred_answers:", ex["pred_answers"])
            print("answer_clusters:", ex["answer_clusters"])
            print("correct:", ex["correct"])