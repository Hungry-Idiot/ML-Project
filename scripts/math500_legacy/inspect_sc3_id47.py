import json
from pathlib import Path

IN_PATH = Path("outputs/sc3_valid47.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        if ex["id"] == 47:
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("pred_answers:", ex["pred_answers"])
            print("selected_answer:", ex["selected_answer"])
            print("correct:", ex["correct"])

            print("\n--- raw outputs tail ---")
            for i, raw in enumerate(ex["raw_outputs"]):
                print(f"\nSample {i + 1}:")
                print((raw or "")[-500:])