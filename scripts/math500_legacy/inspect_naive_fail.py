import json
from pathlib import Path

IN_PATH = Path("outputs/naive_delm_valid18.jsonl")

with IN_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)

        if ex.get("pred_answer") is None or not ex.get("correct"):
            print("\n==============================")
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("agent1_answer:", ex.get("agent1_answer"))
            print("agent2_answer:", ex.get("agent2_answer"))
            print("selected_answer:", ex.get("selected_answer"))
            print("correct:", ex.get("correct"))

            print("\n--- agent1_output tail ---")
            print((ex.get("agent1_output") or "")[-1000:])

            print("\n--- agent2_output tail ---")
            print((ex.get("agent2_output") or "")[-1000:])