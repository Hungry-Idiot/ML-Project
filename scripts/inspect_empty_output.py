import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

with path.open("r", encoding="utf-8") as f:
    for line in f:
        ex = json.loads(line)
        if ex.get("pred_answer") is None:
            raw = ex.get("raw_output")
            print("\n==============================")
            print("id:", ex["id"])
            print("gold:", ex["gold"])
            print("raw_output repr:", repr(raw))
            print("raw_output length:", len(raw) if raw is not None else None)