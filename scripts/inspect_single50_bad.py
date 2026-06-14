import json
from pathlib import Path

IN_PATH = Path("outputs/single_50.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        if ex.get("pred_answer") is None or not ex.get("correct"):
            print("\n==============================")
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("pred_answer:", ex.get("pred_answer"))
            print("correct:", ex.get("correct"))
            print("\n--- raw_output tail ---")
            print((ex.get("raw_output") or "")[-1000:])