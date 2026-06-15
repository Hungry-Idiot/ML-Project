import os
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


DATA_PATH = Path("data/AMO-Bench/test.jsonl")
IDS_PATH = Path("outputs/amo_parser_ids.txt")

OUT_PATH = Path("outputs/amo_parser_answer_cluster.jsonl")
ERROR_PATH = Path("outputs/amo_parser_answer_cluster_api_errors.jsonl")

NUM_AGENTS = int(os.getenv("AC_NUM_AGENTS", "3"))
MAX_TOKENS = int(os.getenv("AMO_AC_MAX_TOKENS", "8192"))
TEMPERATURE = float(os.getenv("AMO_AC_TEMPERATURE", "0.7"))
SLEEP_SECONDS = float(os.getenv("AMO_AC_SLEEP", "0.5"))

# 调试用：AC_LIMIT=3 先跑 3 题，确认没问题后再跑完整 39 题。
LIMIT = int(os.getenv("AC_LIMIT", "0"))


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


def read_ids(path: Path) -> set[int]:
    if not path.exists():
        raise FileNotFoundError(
            f"ID file not found: {path}\n"
            "Please run scripts/make_amo_parser_ids.py first."
        )

    ids = set()

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(int(line))

    return ids


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


def cluster_to_text(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "No answer clusters yet."

    lines = []

    for i, c in enumerate(clusters):
        lines.append(
            f"Cluster {i}: answer = {c['canonical_answer']}, "
            f"support = {c['support_count']}"
        )

        members = c.get("members", [])
        member_names = [m.get("agent_name", f"agent{m.get('agent_id')}") for m in members]
        lines.append(f"  supported_by = {member_names}")

    return "\n".join(lines)


def add_to_clusters(
    clusters: list[dict[str, Any]],
    answer: str | None,
    *,
    agent_id: int,
    agent_name: str,
    raw_output: str,
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """
    Add one agent answer into current answer clusters.

    Return:
    - updated clusters
    - matched cluster index, or None if no valid answer
    - whether a new cluster was created
    """
    answer = normalize_answer(answer)

    if answer is None:
        return clusters, None, False

    for idx, cluster in enumerate(clusters):
        canonical = cluster["canonical_answer"]

        if equivalent(canonical, answer):
            cluster["members"].append({
                "agent_id": agent_id,
                "agent_name": agent_name,
                "answer": answer,
                "raw_output_tail": raw_output[-1200:] if raw_output else "",
            })
            cluster["support_count"] += 1
            return clusters, idx, False

    new_cluster = {
        "canonical_answer": answer,
        "support_count": 1,
        "first_seen_agent_id": agent_id,
        "members": [
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "answer": answer,
                "raw_output_tail": raw_output[-1200:] if raw_output else "",
            }
        ],
    }

    clusters.append(new_cluster)
    return clusters, len(clusters) - 1, True


def sort_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Highest support first; ties broken by earliest agent.
    """
    return sorted(
        clusters,
        key=lambda c: (
            -int(c.get("support_count", 0)),
            int(c.get("first_seen_agent_id", 10**9)),
        ),
    )


def choose_from_clusters(clusters: list[dict[str, Any]]) -> tuple[str | None, int, list[dict[str, Any]]]:
    clusters = sort_clusters(clusters)

    if not clusters:
        return None, 0, []

    best = clusters[0]
    return best["canonical_answer"], best["support_count"], clusters


def build_prompt(problem: str, agent_id: int, clusters: list[dict[str, Any]]) -> str:
    """
    Agent 1 solves independently.
    Later agents see only compact answer clusters, not full previous reasoning.
    This is important: shared context is compact verified context, not raw trace copying.
    """
    if agent_id == 1:
        return f"""
You are Agent {agent_id} solving a very hard olympiad-style math problem.

Please solve the problem carefully. You may show your reasoning.

At the end of your response, output the final answer in exactly this format:

Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    cluster_context = cluster_to_text(clusters)

    return f"""
You are Agent {agent_id} solving a very hard olympiad-style math problem.

You are given a compact shared context from previous agents.
The shared context contains answer clusters only. Each cluster is a candidate final answer and its support count.

Important instructions:
- Do not blindly copy the existing clusters.
- First, solve or verify the problem yourself.
- Then compare your conclusion with the current answer clusters.
- If an existing cluster seems correct, you may support it by outputting the same final answer.
- If all existing clusters seem wrong, propose a new final answer.
- You may show your reasoning.
- At the end of your response, output the final answer in exactly this format:

Final Answer: \\boxed{{your_answer}}

Current shared answer clusters:
{cluster_context}

Problem:
{problem}
"""


def call_agent(client, problem: str, agent_id: int, clusters: list[dict[str, Any]]) -> dict[str, Any]:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    prompt = build_prompt(problem, agent_id, clusters)

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
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

    target_ids = read_ids(IDS_PATH)
    all_data = read_jsonl(DATA_PATH)

    data = [ex for ex in all_data if ex["id"] in target_ids]
    data.sort(key=lambda x: x["id"])

    if LIMIT > 0:
        data = data[:LIMIT]

    client = get_client()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    done_ids = load_done_ids(OUT_PATH)

    total_seen, correct_seen = summarize_existing(OUT_PATH)

    print("Dataset:", DATA_PATH)
    print("ID file:", IDS_PATH)
    print("Output:", OUT_PATH)
    print("Error log:", ERROR_PATH)
    print("Target examples:", len(data))
    print("Already done:", len(done_ids))
    print("Num agents:", NUM_AGENTS)
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
                f"\n===== AMO-P Answer-Cluster Problem {n}/{len(data)}, "
                f"id={idx}, question_id={ex.get('question_id')}, "
                f"type={ex.get('answer_type')} ====="
            )

            clusters: list[dict[str, Any]] = []
            agent_records: list[dict[str, Any]] = []
            agent_answers: list[str | None] = []
            had_api_error = False

            for agent_id in range(1, NUM_AGENTS + 1):
                agent_name = f"agent{agent_id}"

                print(f"\n--- {agent_name} ---")
                print("current clusters before call:")
                print(cluster_to_text(sort_clusters(clusters)))

                result = call_agent(client, problem, agent_id, sort_clusters(clusters))

                raw_output = result.get("content", "")
                finish_reason = result.get("finish_reason")
                usage = result.get("usage")
                error = result.get("error")

                if error is not None or finish_reason == "api_error":
                    had_api_error = True

                pred_answer = extract_boxed(raw_output)
                pred_answer = normalize_answer(pred_answer)

                agent_answers.append(pred_answer)

                clusters, matched_cluster_idx, created_new_cluster = add_to_clusters(
                    clusters,
                    pred_answer,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    raw_output=raw_output,
                )
                clusters = sort_clusters(clusters)

                agent_record = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "raw_output": raw_output,
                    "pred_answer": pred_answer,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "error": error,
                    "matched_cluster_idx_after_sort": None,
                    "created_new_cluster": created_new_cluster,
                    "clusters_after_agent": clusters,
                }

                # 重新定位排序后的 cluster index，方便后面分析。
                if pred_answer is not None:
                    for ci, c in enumerate(clusters):
                        if any(
                            m.get("agent_id") == agent_id
                            for m in c.get("members", [])
                        ):
                            agent_record["matched_cluster_idx_after_sort"] = ci
                            break

                agent_records.append(agent_record)

                print("pred_answer:", pred_answer)
                print("finish_reason:", finish_reason)
                if error:
                    print("error:", error)
                if usage is not None:
                    print("usage:", usage)

                print("clusters after call:")
                print(cluster_to_text(clusters))

                time.sleep(SLEEP_SECONDS)

            # 出现 API error 时不写入主结果，避免把服务错误当成模型错误。
            # 下次重新运行脚本会自动重跑这道题。
            if had_api_error:
                error_record = {
                    "id": idx,
                    "question_id": ex.get("question_id"),
                    "answer_type": ex.get("answer_type"),
                    "gold": gold,
                    "agent_records": agent_records,
                    "answer_clusters": clusters,
                    "note": "Skipped from main output because at least one agent had api_error.",
                }
                err_f.write(json.dumps(error_record, ensure_ascii=False) + "\n")
                err_f.flush()

                print("[SKIP] API error occurred. This problem was not saved to main output.")
                print("[SKIP] It will be rerun next time.")
                continue

            selected_answer, selected_support, clusters = choose_from_clusters(clusters)
            is_correct = safe_verify(gold, selected_answer)

            raw_unique_answers = {
                normalize_answer(a)
                for a in agent_answers
                if normalize_answer(a) is not None
            }

            record = {
                "id": idx,
                "question_id": ex.get("question_id"),
                "answer_type": ex.get("answer_type"),
                "problem": problem,
                "gold": gold,

                "agent_records": agent_records,
                "agent_answers": agent_answers,
                "answer_clusters": clusters,

                "selected_answer": selected_answer,
                "pred_answer": selected_answer,  # 兼容通用 analyze_results.py
                "selected_support": selected_support,
                "correct": is_correct,

                "num_agents": NUM_AGENTS,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "method": "Answer-Cluster-DeLM",

                "num_clusters": len(clusters),
                "raw_unique_answer_count": len(raw_unique_answers),
                "has_raw_disagreement": len(raw_unique_answers) > 1,
                "has_cluster_disagreement": len(clusters) > 1,
            }

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()

            total_seen += 1
            correct_seen += int(is_correct)

            print("\n--- selected ---")
            print("gold:", gold)
            print("agent_answers:", agent_answers)
            print("selected_answer:", selected_answer)
            print("selected_support:", selected_support)
            print("num_clusters:", len(clusters))
            print("correct:", is_correct)
            print("running accuracy:", pct(correct_seen, total_seen))

    records = read_jsonl(OUT_PATH)
    total = len(records)
    correct = sum(1 for ex in records if ex.get("correct") is True)
    parse_fail = sum(1 for ex in records if ex.get("selected_answer") is None)
    parse_success = total - parse_fail

    support_counter = Counter(ex.get("selected_support") for ex in records)
    cluster_counter = Counter(ex.get("num_clusters") for ex in records)
    raw_disagreement = sum(1 for ex in records if ex.get("has_raw_disagreement") is True)
    cluster_disagreement = sum(1 for ex in records if ex.get("has_cluster_disagreement") is True)

    print("\n=== AMO-P Answer-Cluster Results ===")
    print("File:", OUT_PATH)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", pct(correct, total))
    print("Parse fail:", parse_fail)
    print("Parse success:", pct(parse_success, total))
    print("Raw disagreement problems:", raw_disagreement)
    print("Cluster disagreement problems:", cluster_disagreement)

    print("\n=== selected_support distribution ===")
    for k, v in sorted(support_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")

    print("\n=== num_clusters distribution ===")
    for k, v in sorted(cluster_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()