import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    get_client,
    extract_boxed,
    safe_verify,
    call_llm_final_only,
)

IDS_PATH = Path("outputs/amo_parser_ids.txt")
DATA_PATH = Path("data/AMO-Bench/test.jsonl")
OUT_PATH = Path("outputs/amo_parser_single.jsonl")

# AMO 比 MATH-500 难很多，默认给大一点。
# 如果你的供应商不支持这么高，会报错；可以在命令行用环境变量调低。
MAX_TOKENS = int(os.getenv("AMO_MAX_TOKENS", "16000"))
RETRY = int(os.getenv("AMO_RETRY", "1"))
TEMPERATURE = float(os.getenv("AMO_TEMPERATURE", "0.7"))

def read_ids(path: Path):
    if not path.exists():
        return None

    ids = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(int(line))

    return set(ids)


def read_jsonl(path: Path):
    records = []
    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    return records


def load_done_ids(path: Path):
    done_ids = set()

    for ex in read_jsonl(path):
        done_ids.add(ex["id"])

    return done_ids


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Input file not found: {DATA_PATH}")

    data = read_jsonl(DATA_PATH)
    client = get_client()
    target_ids = read_ids(IDS_PATH)

    if target_ids is not None:
        data = [ex for ex in data if ex["id"] in target_ids]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_done_ids(OUT_PATH)

    print("Dataset:", DATA_PATH)
    print("Total examples:", len(data))
    print("Already done:", len(done_ids))
    print("Output:", OUT_PATH)
    print("Max tokens:", MAX_TOKENS)
    print("Retry:", RETRY)
    print("Temperature:", TEMPERATURE)

    old_records = read_jsonl(OUT_PATH)
    total_seen = len(old_records)
    correct_seen = sum(1 for ex in old_records if ex.get("correct") is True)

    with OUT_PATH.open("a", encoding="utf-8") as f:
        for n, ex in enumerate(data, start=1):
            idx = ex["id"]

            if idx in done_ids:
                continue

            problem = ex["problem"]
            gold = ex["gold"]

            print(
                f"\n===== AMO Problem {n}/{len(data)}, "
                f"id={idx}, question_id={ex.get('question_id')} ====="
            )

            result = call_llm_final_only(
                client,
                problem,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                retry=RETRY,
            )

            raw_output = result.get("content", "")
            finish_reason = result.get("finish_reason")
            usage = result.get("usage")

            pred_answer = extract_boxed(raw_output)
            is_correct = safe_verify(gold, pred_answer)

            record = {
                "id": idx,
                "question_id": ex.get("question_id"),
                "answer_type": ex.get("answer_type"),
                "problem": problem,
                "gold": gold,
                "raw_output": raw_output,
                "pred_answer": pred_answer,
                "correct": is_correct,
                "finish_reason": finish_reason,
                "usage": usage,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            }

            if finish_reason == "api_error" or result.get("error"):
                print("[SKIP] API error, do not save this example. Please rerun later.")
                continue

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            total_seen += 1
            correct_seen += int(is_correct)

            print("gold:", gold)
            print("pred_answer:", pred_answer)
            print("correct:", is_correct)
            print("finish_reason:", finish_reason)

            if usage is not None:
                print("usage:", usage)

            print("running accuracy:", f"{correct_seen / total_seen:.2%}")

    records = read_jsonl(OUT_PATH)
    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in records if ex.get("pred_answer") is None)
    length_fail = sum(1 for ex in records if ex.get("finish_reason") == "length")

    print("\n=== AMO Single-CoT Results ===")
    print("File:", OUT_PATH)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
    print("Parse fail:", parse_fail)
    print("Parse success:", f"{(total - parse_fail) / total:.2%}" if total else "N/A")
    print("Length fail:", length_fail)


if __name__ == "__main__":
    main()