import json
from pathlib import Path
from math_verify import parse, verify

IN_PATH = Path("outputs/sc3_valid18.jsonl")
OUT_PATH = Path("outputs/sc3_clusters_valid18.jsonl")


def equivalent(ans1: str | None, ans2: str | None) -> bool:
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


def cluster_answers(pred_answers):
    clusters = []

    for ans in pred_answers:
        if ans is None:
            continue

        placed = False

        for cluster in clusters:
            if equivalent(ans, cluster["canonical_answer"]):
                cluster["members"].append(ans)
                cluster["support_count"] += 1
                placed = True
                break

        if not placed:
            clusters.append({
                "canonical_answer": ans,
                "members": [ans],
                "support_count": 1,
            })

    clusters.sort(key=lambda x: x["support_count"], reverse=True)
    return clusters


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    all_same_raw = 0
    all_same_cluster = 0
    has_disagreement = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            ex = json.loads(line)
            total += 1

            pred_answers = ex["pred_answers"]
            valid_answers = [a for a in pred_answers if a is not None]

            raw_unique = set(valid_answers)
            clusters = cluster_answers(pred_answers)

            if len(raw_unique) == 1:
                all_same_raw += 1

            if len(clusters) == 1:
                all_same_cluster += 1

            if len(clusters) > 1:
                has_disagreement += 1

            ex["answer_clusters"] = clusters
            ex["num_raw_unique_answers"] = len(raw_unique)
            ex["num_equiv_clusters"] = len(clusters)

            fout.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print("Saved to", OUT_PATH)
    print("Total:", total)
    print("All same raw string:", all_same_raw)
    print("All same after equivalence clustering:", all_same_cluster)
    print("Has disagreement after clustering:", has_disagreement)


if __name__ == "__main__":
    main()