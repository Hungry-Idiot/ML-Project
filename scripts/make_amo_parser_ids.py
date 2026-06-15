import json
from pathlib import Path
from collections import Counter


DATA_PATH = Path("data/AMO-Bench/test.jsonl")
PARSER_IDS_PATH = Path("outputs/amo_parser_ids.txt")
DESC_IDS_PATH = Path("outputs/amo_description_ids.txt")


PARSER_TYPES = {"number", "set", "variable"}


def main():
    records = []

    with DATA_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    counter = Counter(ex.get("answer_type") for ex in records)

    print("=== answer_type distribution ===")
    for k, v in counter.items():
        print(repr(k), ":", v)

    parser_ids = []
    desc_ids = []

    for ex in records:
        answer_type = ex.get("answer_type")

        if answer_type in PARSER_TYPES:
            parser_ids.append(ex["id"])
        else:
            desc_ids.append(ex["id"])

    PARSER_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with PARSER_IDS_PATH.open("w", encoding="utf-8") as f:
        for idx in parser_ids:
            f.write(str(idx) + "\n")

    with DESC_IDS_PATH.open("w", encoding="utf-8") as f:
        for idx in desc_ids:
            f.write(str(idx) + "\n")

    print("\nParser subset count:", len(parser_ids))
    print("Parser ids:", parser_ids)
    print("Saved to:", PARSER_IDS_PATH)

    print("\nDescription subset count:", len(desc_ids))
    print("Description ids:", desc_ids)
    print("Saved to:", DESC_IDS_PATH)


if __name__ == "__main__":
    main()