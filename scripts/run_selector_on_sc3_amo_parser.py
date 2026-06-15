import os
import re
import sys
import json
import time
from pathlib import Path
from typing import Any
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    get_client,
    extract_boxed,
    safe_verify,
    equivalent,
)


SC3_PATH = Path("outputs/amo_parser_sc3.jsonl")
OUT_PATH = Path("outputs/amo_parser_selector_on_sc3.jsonl")
ERROR_PATH = Path("outputs/amo_parser_selector_on_sc3_api_errors.jsonl")

MAX_TOKENS = int(os.getenv("SELECTOR_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("SELECTOR_TEMPERATURE", "0.2"))
SLEEP_SECONDS = float(os.getenv("SELECTOR_SLEEP", "0.5"))

# 调试用：SELECTOR_LIMIT=3 先跑 3 题
LIMIT = int(os.getenv("SELECTOR_LIMIT", "0"))

# 每个 sample 的 raw_output 尾部截取长度。
# 太长会浪费 token；太短又看不到推理结论。
RAW_TAIL_CHARS = int(os.getenv("SELECTOR_RAW_TAIL_CHARS", "1200"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []

    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    return records


def load_done_ids(path: Path) -> set[int]:
    done = set()

    for ex in read_jsonl(path):
        if "id" in ex:
            done.add(ex["id"])

    return done


def response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return {"raw": str(usage)}


def normalize_answer(ans: str | None) -> str | None:
    if ans is None:
        return None

    ans = str(ans).strip()

    if not ans:
        return None

    return ans


def get_pred_answers(ex: dict[str, Any]) -> list[str | None]:
    if "pred_answers" in ex and isinstance(ex["pred_answers"], list):
        return [normalize_answer(a) for a in ex["pred_answers"]]

    sample_records = ex.get("sample_records", [])
    return [normalize_answer(s.get("pred_answer")) for s in sample_records]


def get_sample_records(ex: dict[str, Any]) -> list[dict[str, Any]]:
    sample_records = ex.get("sample_records", [])
    if isinstance(sample_records, list):
        return sample_records
    return []


def tail_text(text: str | None, max_chars: int) -> str:
    if not text:
        return ""

    text = str(text).strip()

    if len(text) <= max_chars:
        return text

    return text[-max_chars:]


def cluster_answers_from_sc3(ex: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Build math-equivalence answer clusters from SC3 sample answers.

    Cluster format:
    {
        "cluster_id": int,
        "canonical_answer": str,
        "support_count": int,
        "members": [...]
    }
    """
    pred_answers = get_pred_answers(ex)
    sample_records = get_sample_records(ex)

    clusters: list[dict[str, Any]] = []

    for sample_id, ans in enumerate(pred_answers):
        ans = normalize_answer(ans)

        if ans is None:
            continue

        matched = False

        for cluster in clusters:
            if equivalent(cluster["canonical_answer"], ans):
                cluster["members"].append({
                    "sample_id": sample_id,
                    "answer": ans,
                    "finish_reason": (
                        sample_records[sample_id].get("finish_reason")
                        if sample_id < len(sample_records)
                        else None
                    ),
                    "raw_output_tail": (
                        tail_text(sample_records[sample_id].get("raw_output"), RAW_TAIL_CHARS)
                        if sample_id < len(sample_records)
                        else ""
                    ),
                })
                cluster["support_count"] += 1
                matched = True
                break

        if not matched:
            clusters.append({
                "cluster_id": len(clusters),
                "canonical_answer": ans,
                "support_count": 1,
                "first_seen_sample_id": sample_id,
                "members": [
                    {
                        "sample_id": sample_id,
                        "answer": ans,
                        "finish_reason": (
                            sample_records[sample_id].get("finish_reason")
                            if sample_id < len(sample_records)
                            else None
                        ),
                        "raw_output_tail": (
                            tail_text(sample_records[sample_id].get("raw_output"), RAW_TAIL_CHARS)
                            if sample_id < len(sample_records)
                            else ""
                        ),
                    }
                ],
            })

    clusters.sort(
        key=lambda c: (
            -int(c.get("support_count", 0)),
            int(c.get("first_seen_sample_id", 10**9)),
        )
    )

    # 排序后重新编号，避免 prompt 中 cluster id 和列表位置不一致。
    for new_id, cluster in enumerate(clusters):
        cluster["cluster_id"] = new_id

    return clusters


def clusters_to_prompt_text(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "No valid candidate clusters."

    blocks = []

    for cluster in clusters:
        lines = []
        lines.append(f"Candidate Cluster {cluster['cluster_id']}")
        lines.append(f"Canonical answer: {cluster['canonical_answer']}")
        lines.append(f"Support count: {cluster['support_count']}")
        lines.append("Supporting samples:")

        for member in cluster.get("members", []):
            lines.append(f"- Sample {member.get('sample_id')}: answer = {member.get('answer')}")
            tail = member.get("raw_output_tail") or ""
            if tail:
                lines.append("  Reasoning/output tail:")
                lines.append("  " + tail.replace("\n", "\n  "))

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def build_selector_prompt(problem: str, clusters: list[dict[str, Any]]) -> str:
    cluster_text = clusters_to_prompt_text(clusters)

    return f"""
You are a selector/verifier agent for a very hard olympiad-style math problem.

You are given:
1. The original problem.
2. Several candidate answer clusters produced by independent solver agents.
3. Each cluster's support count and short supporting output tails.

Your task:
- Do NOT solve from scratch unless needed for verification.
- Compare the candidate clusters carefully.
- Check whether the supporting reasoning appears valid or contains mistakes.
- Choose the single most reliable candidate cluster.
- You must choose one of the given candidate clusters.
- Do not invent a new answer outside the candidate clusters.
- Support count is useful but not decisive. A majority can still be wrong.

Output format:
Selected Cluster: <cluster_id>
Final Answer: \\boxed{{answer_from_that_cluster}}

Problem:
{problem}

Candidate answer clusters:
{cluster_text}
"""


def call_selector(client, problem: str, clusters: list[dict[str, Any]]) -> dict[str, Any]:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    prompt = build_selector_prompt(problem, clusters)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

        choice = resp.choices[0]
        content = choice.message.content or ""
        finish_reason = choice.finish_reason
        usage = response_usage_to_dict(getattr(resp, "usage", None))

        return {
            "content": content,
            "finish_reason": finish_reason,
            "usage": usage,
            "error": None,
        }

    except Exception as e:
        return {
            "content": "",
            "finish_reason": "api_error",
            "usage": None,
            "error": repr(e),
        }


def parse_selected_cluster_id(text: str | None) -> int | None:
    if not text:
        return None

    patterns = [
        r"Selected\s*Cluster\s*:\s*(\d+)",
        r"Cluster\s*:\s*(\d+)",
        r"selected\s*cluster\s*is\s*(\d+)",
        r"candidate\s*cluster\s*(\d+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None

    return None


def find_matching_cluster_by_answer(
    selected_answer: str | None,
    clusters: list[dict[str, Any]],
) -> int | None:
    selected_answer = normalize_answer(selected_answer)

    if selected_answer is None:
        return None

    for cluster in clusters:
        canonical = cluster.get("canonical_answer")
        if equivalent(canonical, selected_answer):
            return cluster.get("cluster_id")

    return None


def choose_fallback_by_support(clusters: list[dict[str, Any]]) -> tuple[str | None, int | None, int]:
    if not clusters:
        return None, None, 0

    best = clusters[0]
    return best.get("canonical_answer"), best.get("cluster_id"), best.get("support_count", 0)


def pct(x: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{x / total:.2%}"


def summarize_existing(path: Path) -> tuple[int, int]:
    records = read_jsonl(path)
    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    return total, correct


def main():
    if not SC3_PATH.exists():
        raise FileNotFoundError(f"SC3 file not found: {SC3_PATH}")

    records = read_jsonl(SC3_PATH)
    records.sort(key=lambda x: x["id"])

    if LIMIT > 0:
        records = records[:LIMIT]

    client = get_client()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_done_ids(OUT_PATH)

    total_seen, correct_seen = summarize_existing(OUT_PATH)

    print("Input SC3 file:", SC3_PATH)
    print("Output:", OUT_PATH)
    print("Error log:", ERROR_PATH)
    print("Target examples:", len(records))
    print("Already done:", len(done_ids))
    print("Max tokens:", MAX_TOKENS)
    print("Temperature:", TEMPERATURE)
    print("Raw tail chars:", RAW_TAIL_CHARS)
    print("Limit:", LIMIT if LIMIT > 0 else "None")

    with OUT_PATH.open("a", encoding="utf-8") as out_f, ERROR_PATH.open("a", encoding="utf-8") as err_f:
        for n, ex in enumerate(records, start=1):
            idx = ex["id"]

            if idx in done_ids:
                continue

            problem = ex["problem"]
            gold = ex["gold"]

            print(
                f"\n===== Selector-on-SC3 Problem {n}/{len(records)}, "
                f"id={idx}, question_id={ex.get('question_id')}, "
                f"type={ex.get('answer_type')} ====="
            )

            clusters = cluster_answers_from_sc3(ex)

            print("Candidate clusters:")
            for c in clusters:
                print(
                    f"Cluster {c['cluster_id']}: "
                    f"answer={c['canonical_answer']}, "
                    f"support={c['support_count']}"
                )

            if not clusters:
                selected_answer = None
                selected_cluster_id = None
                selected_support = 0
                selector_result = {
                    "content": "",
                    "finish_reason": "no_candidate_cluster",
                    "usage": None,
                    "error": None,
                }
                used_fallback = True
            else:
                selector_result = call_selector(client, problem, clusters)

                if selector_result.get("error") is not None or selector_result.get("finish_reason") == "api_error":
                    error_record = {
                        "id": idx,
                        "question_id": ex.get("question_id"),
                        "answer_type": ex.get("answer_type"),
                        "gold": gold,
                        "clusters": clusters,
                        "selector_result": selector_result,
                        "note": "Skipped from main output because selector had api_error.",
                    }
                    err_f.write(json.dumps(error_record, ensure_ascii=False) + "\n")
                    err_f.flush()

                    print("[SKIP] API error occurred. This problem was not saved to main output.")
                    print("[SKIP] It will be rerun next time.")
                    time.sleep(SLEEP_SECONDS)
                    continue

                selector_output = selector_result.get("content", "")

                parsed_cluster_id = parse_selected_cluster_id(selector_output)
                parsed_answer = normalize_answer(extract_boxed(selector_output))

                selected_cluster_id = None
                selected_answer = None
                selected_support = 0
                used_fallback = False

                # 优先相信显式 cluster id，但必须合法。
                if parsed_cluster_id is not None and 0 <= parsed_cluster_id < len(clusters):
                    selected_cluster_id = parsed_cluster_id
                    selected_answer = clusters[selected_cluster_id]["canonical_answer"]
                    selected_support = clusters[selected_cluster_id]["support_count"]
                else:
                    # 如果 cluster id 没抽到，尝试用 boxed answer 反查 cluster。
                    matched_id = find_matching_cluster_by_answer(parsed_answer, clusters)
                    if matched_id is not None:
                        selected_cluster_id = matched_id
                        selected_answer = clusters[selected_cluster_id]["canonical_answer"]
                        selected_support = clusters[selected_cluster_id]["support_count"]
                    else:
                        # 兜底：不让模型发明新答案，退回 support 最大 cluster。
                        selected_answer, selected_cluster_id, selected_support = choose_fallback_by_support(clusters)
                        used_fallback = True

            is_correct = safe_verify(gold, selected_answer)

            raw_vote_answer = ex.get("selected_answer")
            raw_vote_correct = safe_verify(gold, raw_vote_answer)

            # Oracle@3：只要 SC3 三个候选中有一个正确就算 oracle 正确。
            pred_answers = get_pred_answers(ex)
            oracle_correct = any(safe_verify(gold, a) for a in pred_answers)

            record = {
                "id": idx,
                "question_id": ex.get("question_id"),
                "answer_type": ex.get("answer_type"),
                "problem": problem,
                "gold": gold,

                "source_method": "SC3-RawVote",
                "method": "DELM-lite-Selector-on-SC3",

                "sc3_pred_answers": pred_answers,
                "sc3_raw_vote_answer": raw_vote_answer,
                "sc3_raw_vote_correct": raw_vote_correct,
                "sc3_oracle_at_3_correct": oracle_correct,

                "clusters": clusters,
                "num_clusters": len(clusters),

                "selector_raw_output": selector_result.get("content", ""),
                "selector_finish_reason": selector_result.get("finish_reason"),
                "selector_usage": selector_result.get("usage"),
                "selector_error": selector_result.get("error"),

                "selected_cluster_id": selected_cluster_id,
                "selected_support": selected_support,
                "selected_answer": selected_answer,
                "pred_answer": selected_answer,  # 兼容通用 analyze_results.py
                "correct": is_correct,

                "used_fallback": used_fallback,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            }

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()

            total_seen += 1
            correct_seen += int(is_correct)

            print("gold:", gold)
            print("raw_vote_answer:", raw_vote_answer)
            print("raw_vote_correct:", raw_vote_correct)
            print("oracle_correct:", oracle_correct)
            print("selected_cluster_id:", selected_cluster_id)
            print("selected_answer:", selected_answer)
            print("selected_support:", selected_support)
            print("correct:", is_correct)
            print("used_fallback:", used_fallback)
            print("finish_reason:", selector_result.get("finish_reason"))
            print("running accuracy:", pct(correct_seen, total_seen))

            time.sleep(SLEEP_SECONDS)

    final_records = read_jsonl(OUT_PATH)
    total = len(final_records)
    correct = sum(1 for ex in final_records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in final_records if ex.get("selected_answer") is None)
    fallback_count = sum(1 for ex in final_records if ex.get("used_fallback") is True)

    raw_vote_correct = sum(1 for ex in final_records if ex.get("sc3_raw_vote_correct") is True)
    oracle_correct = sum(1 for ex in final_records if ex.get("sc3_oracle_at_3_correct") is True)

    recovers_raw = sum(
        1 for ex in final_records
        if ex.get("correct") is True and ex.get("sc3_raw_vote_correct") is not True
    )
    regresses_raw = sum(
        1 for ex in final_records
        if ex.get("correct") is not True and ex.get("sc3_raw_vote_correct") is True
    )
    raw_missed_oracle = sum(
        1 for ex in final_records
        if ex.get("sc3_oracle_at_3_correct") is True and ex.get("sc3_raw_vote_correct") is not True
    )
    selector_missed_oracle = sum(
        1 for ex in final_records
        if ex.get("sc3_oracle_at_3_correct") is True and ex.get("correct") is not True
    )

    support_counter = Counter(ex.get("selected_support") for ex in final_records)
    cluster_counter = Counter(ex.get("num_clusters") for ex in final_records)

    print("\n=== DELM-lite Selector-on-SC3 Results ===")
    print("File:", OUT_PATH)
    print("Total:", total)

    print("\n--- Main accuracies on same subset ---")
    print("SC3-RawVote Correct:", raw_vote_correct, pct(raw_vote_correct, total))
    print("Oracle@3 Correct:", oracle_correct, pct(oracle_correct, total))
    print("Selector Correct:", correct, pct(correct, total))

    print("\n--- Diagnostics ---")
    print("Parse fail:", parse_fail)
    print("Parse success:", pct(total - parse_fail, total))
    print("Fallback count:", fallback_count)
    print("Selector recovers RawVote failures:", recovers_raw)
    print("Selector regresses RawVote successes:", regresses_raw)
    print("RawVote missed Oracle@3:", raw_missed_oracle)
    print("Selector missed Oracle@3:", selector_missed_oracle)

    print("\n=== selected_support distribution ===")
    for k, v in sorted(support_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")

    print("\n=== num_clusters distribution ===")
    for k, v in sorted(cluster_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()