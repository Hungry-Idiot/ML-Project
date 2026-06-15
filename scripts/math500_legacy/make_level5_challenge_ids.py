import json
from pathlib import Path


IN_PATH = Path("outputs/single_level5_fixed.jsonl")

OUT_ALL = Path("outputs/challenge_ids_level5.txt")
OUT_PARSE_FAIL = Path("outputs/challenge_ids_level5_parsefail.txt")
OUT_WRONG = Path("outputs/challenge_ids_level5_wrong.txt")
OUT_CASES = Path("outputs/challenge_cases_level5.jsonl")


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input file not found: {IN_PATH}")

    challenge_ids = []
    parsefail_ids = []
    wrong_ids = []
    challenge_cases = []

    total = 0
    correct = 0
    parse_fail = 0
    wrong_non_parse = 0

    with IN_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            ex = json.loads(line)
            total += 1

            idx = ex["id"]
            pred_answer = ex.get("pred_answer")
            is_correct = ex.get("correct") is True

            if is_correct:
                correct += 1

            is_parse_fail = pred_answer is None
            is_wrong = (pred_answer is not None) and (not is_correct)

            if is_parse_fail:
                parse_fail += 1
                parsefail_ids.append(idx)

            if is_wrong:
                wrong_non_parse += 1
                wrong_ids.append(idx)

            if is_parse_fail or is_wrong:
                challenge_ids.append(idx)

                case = {
                    "id": idx,
                    "level": ex.get("level"),
                    "type": ex.get("type"),
                    "gold": ex.get("gold"),
                    "pred_answer": pred_answer,
                    "correct": is_correct,
                    "case_type": "parse_fail" if is_parse_fail else "wrong_answer",
                    "problem": ex.get("problem"),
                    "raw_output": ex.get("raw_output"),
                }
                challenge_cases.append(case)

    OUT_ALL.parent.mkdir(parents=True, exist_ok=True)

    OUT_ALL.write_text(
        "\n".join(map(str, challenge_ids)) + "\n",
        encoding="utf-8"
    )

    OUT_PARSE_FAIL.write_text(
        "\n".join(map(str, parsefail_ids)) + "\n",
        encoding="utf-8"
    )

    OUT_WRONG.write_text(
        "\n".join(map(str, wrong_ids)) + "\n",
        encoding="utf-8"
    )

    with OUT_CASES.open("w", encoding="utf-8") as f:
        for ex in challenge_cases:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print("Input:", IN_PATH)
    print("Total:", total)
    print("Correct:", correct)
    print("Parse fail:", parse_fail)
    print("Wrong non-parse:", wrong_non_parse)

    print("\n=== Challenge Subset ===")
    print("Challenge count:", len(challenge_ids))
    print("Challenge ids:", challenge_ids)

    print("\nParse-fail ids:", parsefail_ids)
    print("Wrong-answer ids:", wrong_ids)

    print("\nSaved:")
    print("-", OUT_ALL)
    print("-", OUT_PARSE_FAIL)
    print("-", OUT_WRONG)
    print("-", OUT_CASES)


if __name__ == "__main__":
    main()