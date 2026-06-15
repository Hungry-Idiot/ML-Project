import json
from pathlib import Path

from math_verify import parse, verify


IN_PATH = Path("outputs/sc3_valid47.jsonl")
OUT_PATH = Path("outputs/sc3_equiv_cluster_valid47.jsonl")


def equivalent(ans1: str | None, ans2: str | None) -> bool:
    """
    判断两个答案是否数学等价。
    这里会尝试几种包装形式，提高 math-verify 的解析成功率。
    """
    if ans1 is None or ans2 is None:
        return False

    candidates1 = [
        ans1,
        f"\\boxed{{{ans1}}}",
        f"Final Answer: \\boxed{{{ans1}}}",
    ]

    candidates2 = [
        ans2,
        f"\\boxed{{{ans2}}}",
        f"Final Answer: \\boxed{{{ans2}}}",
    ]

    for a in candidates1:
        for b in candidates2:
            try:
                if verify(parse(a), parse(b)):
                    return True
            except Exception:
                pass

    return False


def safe_verify(gold: str, pred_answer: str | None) -> bool:
    """
    判断预测答案和标准答案是否等价。
    """
    if pred_answer is None:
        return False

    gold_candidates = [
        gold,
        f"\\boxed{{{gold}}}",
        f"Final Answer: \\boxed{{{gold}}}",
    ]

    pred_candidates = [
        pred_answer,
        f"\\boxed{{{pred_answer}}}",
        f"Final Answer: \\boxed{{{pred_answer}}}",
    ]

    for g in gold_candidates:
        for p in pred_candidates:
            try:
                if verify(parse(g), parse(p)):
                    return True
            except Exception:
                pass

    return False


def cluster_answers(pred_answers):
    """
    对 SC3 的三个独立答案做数学等价聚类。

    输入:
        pred_answers: 例如 ['6 - 5i', '6-5i', '6 - 5i']

    输出:
        [
            {
                "canonical_answer": "6 - 5i",
                "members": [
                    {"sample": "sample1", "answer": "6 - 5i"},
                    ...
                ],
                "support_count": 3
            }
        ]
    """
    clusters = []

    for i, ans in enumerate(pred_answers):
        sample_name = f"sample{i + 1}"

        if ans is None:
            continue

        placed = False

        for cluster in clusters:
            if equivalent(ans, cluster["canonical_answer"]):
                cluster["members"].append({
                    "sample": sample_name,
                    "answer": ans,
                })
                cluster["support_count"] += 1
                placed = True
                break

        if not placed:
            clusters.append({
                "canonical_answer": ans,
                "members": [
                    {
                        "sample": sample_name,
                        "answer": ans,
                    }
                ],
                "support_count": 1,
            })

    # Python 的 sort 是稳定排序。
    # 如果 support_count 相同，会保留先出现的 cluster。
    clusters.sort(key=lambda x: x["support_count"], reverse=True)

    return clusters


def choose_from_clusters(clusters):
    """
    选择 support_count 最大的 cluster 的 canonical answer。
    如果没有任何可解析答案，返回 None。
    """
    if not clusters:
        return None

    return clusters[0]["canonical_answer"]


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(
            f"Input file not found: {IN_PATH}\n"
            "Please run scripts/run_sc3_valid47.py first."
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    correct = 0
    parse_fail = 0

    one_cluster = 0
    multi_cluster = 0
    raw_disagree_but_one_cluster = 0
    support_3 = 0
    support_not_3 = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue

            ex = json.loads(line)

            total += 1

            gold = ex["gold"]
            pred_answers = ex.get("pred_answers", [])

            clusters = cluster_answers(pred_answers)
            selected_answer = choose_from_clusters(clusters)
            is_correct = safe_verify(gold, selected_answer)

            if selected_answer is None:
                parse_fail += 1

            correct += int(is_correct)

            valid_answers = [a for a in pred_answers if a is not None]
            raw_unique = set(valid_answers)

            if len(clusters) == 1:
                one_cluster += 1

                if len(raw_unique) > 1:
                    raw_disagree_but_one_cluster += 1

                if clusters[0].get("support_count") == 3:
                    support_3 += 1
                else:
                    support_not_3 += 1

            if len(clusters) > 1:
                multi_cluster += 1

            record = dict(ex)
            record["answer_clusters"] = clusters
            record["selected_answer"] = selected_answer
            record["pred_answer"] = selected_answer
            record["correct"] = is_correct
            record["num_raw_unique_answers"] = len(raw_unique)
            record["num_equiv_clusters"] = len(clusters)

            fout.write(json.dumps(record, ensure_ascii=False) + "\n")

    print("Saved to:", OUT_PATH)
    print("Total:", total)
    print("Correct:", correct)
    print("Accuracy:", f"{correct / total:.2%}" if total else "N/A")
    print("Parse fail:", parse_fail)
    print("Parse success:", f"{(total - parse_fail) / total:.2%}" if total else "N/A")

    print("\n=== Equivalence Cluster Statistics ===")
    print("One-cluster problems:", one_cluster)
    print("Multi-cluster problems:", multi_cluster)
    print("Problems with support_count=3:", support_3)
    print("Problems with support_count not 3:", support_not_3)
    print("Raw disagreement but one equivalent cluster:", raw_disagree_but_one_cluster)


if __name__ == "__main__":
    main()