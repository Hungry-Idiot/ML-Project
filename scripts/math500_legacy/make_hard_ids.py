import json
import re
from pathlib import Path
from collections import Counter


DATA_PATH = Path("data/MATH-500/test.jsonl")

OUT_LEVEL5 = Path("outputs/hard_ids_level5.txt")
OUT_LEVEL45 = Path("outputs/hard_ids_level45.txt")


def parse_level(level_value):
    """
    支持：
    - "Level 5"
    - "level 5"
    - 5
    - "5"
    """
    if level_value is None:
        return None

    if isinstance(level_value, int):
        return level_value

    text = str(level_value)
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())

    return None


def main():
    records = []

    with DATA_PATH.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            ex = json.loads(line)
            level = parse_level(ex.get("level"))
            records.append({
                "id": idx,
                "level": level,
                "raw_level": ex.get("level"),
                "type": ex.get("type"),
            })

    counter = Counter(r["level"] for r in records)

    print("=== Level Distribution ===")
    for level in sorted(counter):
        print(f"Level {level}: {counter[level]}")

    level5_ids = [r["id"] for r in records if r["level"] == 5]
    level45_ids = [r["id"] for r in records if r["level"] in {4, 5}]

    OUT_LEVEL5.parent.mkdir(parents=True, exist_ok=True)

    OUT_LEVEL5.write_text(
        "\n".join(map(str, level5_ids)) + "\n",
        encoding="utf-8"
    )

    OUT_LEVEL45.write_text(
        "\n".join(map(str, level45_ids)) + "\n",
        encoding="utf-8"
    )

    print("\nSaved:", OUT_LEVEL5)
    print("Level 5 count:", len(level5_ids))

    print("\nSaved:", OUT_LEVEL45)
    print("Level 4+5 count:", len(level45_ids))

    print("\nFirst 20 Level 5 ids:")
    print(level5_ids[:20])

    print("\nFirst 20 Level 4+5 ids:")
    print(level45_ids[:20])


if __name__ == "__main__":
    main()