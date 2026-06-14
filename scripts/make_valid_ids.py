import json
from pathlib import Path

in_path = Path("outputs/single_20_v4.jsonl")
out_path = Path("outputs/valid_ids_20.txt")

valid_ids = []

with in_path.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)
        if ex.get("pred_answer") is not None:
            valid_ids.append(ex["id"])

with out_path.open("w", encoding="utf-8") as f:
    for i in valid_ids:
        f.write(str(i) + "\n")

print("Valid ids:", valid_ids)
print("Count:", len(valid_ids))
print("Saved to", out_path)