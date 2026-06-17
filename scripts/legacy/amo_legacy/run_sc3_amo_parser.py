import os
import sys
import json
import time
from pathlib import Path
from collections import Counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    get_client,
    extract_boxed,
    safe_verify,
    call_chat_completion,
    read_jsonl,
    read_ids,
    load_done_ids,
    choose_raw_majority,
    pct,
)


DATA_PATH = Path("data/AMO-Bench/test.jsonl")
IDS_PATH = Path("outputs/amo_parser_ids.txt")
OUT_PATH = Path("outputs/amo_parser_sc3.jsonl")
ERROR_PATH = Path("outputs/amo_parser_sc3_api_errors.jsonl")

NUM_SAMPLES = int(os.getenv("SC3_NUM_SAMPLES", "3"))
MAX_TOKENS = int(os.getenv("AMO_SC3_MAX_TOKENS", "8192"))
TEMPERATURE = float(os.getenv("AMO_SC3_TEMPERATURE", "0.7"))
SLEEP_SECONDS = float(os.getenv("AMO_SC3_SLEEP", "0.5"))

# 调试用：SC3_LIMIT=3 可以先只跑 3 题，确认没问题再全跑。
LIMIT = int(os.getenv("SC3_LIMIT", "0"))


def read_required_ids(path: Path) -> set[int]:
    if not path.exists():
        raise FileNotFoundError(
            f"ID file not found: {path}\n"
            "Please run scripts/make_amo_parser_ids.py first."
        )
    return read_ids(path)


def call_llm_amo(client, problem: str) -> dict[str, Any]:
    """
    One independent model call for SC3.

    Return:
    {
        "content": str,
        "finish_reason": str | None,
        "usage": dict | None,
        "error": str | None,
    }
    """
    prompt = f"""
You are solving a very hard olympiad-style math problem.

Please solve the problem carefully. Keep the visible solution concise.

At the end of your response, output the final answer in exactly this format:

Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    return call_chat_completion(
        client,
        prompt,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

    target_ids = read_required_ids(IDS_PATH)
    all_data = read_jsonl(DATA_PATH)

    data = [ex for ex in all_data if ex["id"] in target_ids]
    data.sort(key=lambda x: x["id"])

    if LIMIT > 0:
        data = data[:LIMIT]

    client = get_client()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_done_ids(OUT_PATH)

    old_records = read_jsonl(OUT_PATH)
    total_seen = len(old_records)
    correct_seen = sum(1 for ex in old_records if ex.get("correct") is True)

    print("Dataset:", DATA_PATH)
    print("ID file:", IDS_PATH)
    print("Output:", OUT_PATH)
    print("Error log:", ERROR_PATH)
    print("Target examples:", len(data))
    print("Already done:", len(done_ids))
    print("Num samples:", NUM_SAMPLES)
    print("Max tokens:", MAX_TOKENS)
    print("Temperature:", TEMPERATURE)
    print("Limit:", LIMIT if LIMIT > 0 else "None")

    with OUT_PATH.open("a", encoding="utf-8") as out_f, ERROR_PATH.open("a", encoding="utf-8") as err_f:
        for n, ex in enumerate(data, start=1):
            idx = ex["id"]

            if idx in done_ids:
                continue

            problem = ex["problem"]
            gold = ex["gold"]

            print(
                f"\n===== AMO-P SC3 Problem {n}/{len(data)}, "
                f"id={idx}, question_id={ex.get('question_id')}, "
                f"type={ex.get('answer_type')} ====="
            )

            sample_records = []
            pred_answers = []

            had_api_error = False

            for s in range(NUM_SAMPLES):
                print(f"\n--- sample {s + 1}/{NUM_SAMPLES} ---")

                result = call_llm_amo(client, problem)

                raw_output = result.get("content", "")
                finish_reason = result.get("finish_reason")
                usage = result.get("usage")
                error = result.get("error")

                if error is not None or finish_reason == "api_error":
                    had_api_error = True

                pred_answer = extract_boxed(raw_output)
                if pred_answer is not None:
                    pred_answer = pred_answer.strip()

                pred_answers.append(pred_answer)

                sample_record = {
                    "sample_id": s,
                    "raw_output": raw_output,
                    "pred_answer": pred_answer,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "error": error,
                }
                sample_records.append(sample_record)

                print("pred_answer:", pred_answer)
                print("finish_reason:", finish_reason)
                if error:
                    print("error:", error)
                if usage is not None:
                    print("usage:", usage)

                time.sleep(SLEEP_SECONDS)

            # 如果出现 API error，不写入主结果文件，避免把网络/服务错误当成模型错误。
            # 下次重新运行脚本时，这道题会自动重跑。
            if had_api_error:
                error_record = {
                    "id": idx,
                    "question_id": ex.get("question_id"),
                    "answer_type": ex.get("answer_type"),
                    "gold": gold,
                    "sample_records": sample_records,
                    "note": "Skipped from main output because at least one sample had api_error.",
                }
                err_f.write(json.dumps(error_record, ensure_ascii=False) + "\n")
                err_f.flush()

                print("[SKIP] API error occurred. This problem was not saved to main output.")
                print("[SKIP] It will be rerun next time.")
                continue

            selected_answer, selected_support, vote_counts = choose_raw_majority(pred_answers)
            is_correct = safe_verify(gold, selected_answer)

            record = {
                "id": idx,
                "question_id": ex.get("question_id"),
                "answer_type": ex.get("answer_type"),
                "problem": problem,
                "gold": gold,
                "sample_records": sample_records,
                "pred_answers": pred_answers,
                "selected_answer": selected_answer,
                "selected_support": selected_support,
                "vote_counts": vote_counts,
                "correct": is_correct,
                "num_samples": NUM_SAMPLES,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "method": "SC3-RawVote",
            }

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()

            total_seen += 1
            correct_seen += int(is_correct)

            print("\n--- selected ---")
            print("gold:", gold)
            print("pred_answers:", pred_answers)
            print("vote_counts:", vote_counts)
            print("selected_answer:", selected_answer)
            print("selected_support:", selected_support)
            print("correct:", is_correct)
            print("running accuracy:", pct(correct_seen, total_seen))

    records = read_jsonl(OUT_PATH)
    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in records if ex.get("selected_answer") is None)
    parse_success = total - parse_fail

    support_counter = Counter(ex.get("selected_support") for ex in records)

    raw_disagreement = 0
    for ex in records:
        valid = [
            str(a).strip()
            for a in ex.get("pred_answers", [])
            if a is not None and str(a).strip()
        ]
        if len(set(valid)) > 1:
            raw_disagreement += 1

    print("\n=== AMO-P SC3-RawVote Results ===")
    print("File:", OUT_PATH)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", pct(correct, total))
    print("Parse fail:", parse_fail)
    print("Parse success:", pct(parse_success, total))
    print("Raw disagreement problems:", raw_disagreement)

    print("\n=== selected_support distribution ===")
    for k, v in sorted(support_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
