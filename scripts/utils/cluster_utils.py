# scripts/utils/cluster_utils.py

from collections import Counter
from typing import Any

from scripts.utils.math_utils import equivalent, normalize_answer


def choose_raw_majority(pred_answers: list[str | None]) -> tuple[str | None, int, dict[str, int]]:
    normalized = [normalize_answer(a) for a in pred_answers]
    valid = [a for a in normalized if a is not None]

    if not valid:
        return None, 0, {}

    counts = Counter(valid)
    max_count = max(counts.values())

    for ans in normalized:
        if ans is not None and counts[ans] == max_count:
            return ans, max_count, dict(counts)

    return None, 0, dict(counts)


def cluster_answers(
    pred_answers: list[str | None],
    *,
    include_members: bool = True,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []

    for i, ans in enumerate(pred_answers):
        ans = normalize_answer(ans)
        if ans is None:
            continue

        matched = False

        for cluster in clusters:
            if equivalent(cluster["canonical_answer"], ans):
                if include_members:
                    cluster["members"].append({
                        "sample_id": i,
                        "answer": ans,
                    })
                cluster["support_count"] += 1
                matched = True
                break

        if not matched:
            clusters.append({
                "canonical_answer": ans,
                "support_count": 1,
                "first_seen": i,
                "members": [{
                    "sample_id": i,
                    "answer": ans,
                }] if include_members else [],
            })

    clusters.sort(key=lambda c: (-c["support_count"], c["first_seen"]))

    for cluster_id, cluster in enumerate(clusters):
        cluster["cluster_id"] = cluster_id

    return clusters


def choose_from_clusters(clusters: list[dict[str, Any]]) -> tuple[str | None, int, list[dict[str, Any]]]:
    if not clusters:
        return None, 0, []

    clusters = sorted(
        clusters,
        key=lambda c: (
            -int(c.get("support_count", 0)),
            int(c.get("first_seen", c.get("first_seen_agent_id", 10**9))),
        ),
    )

    for cluster_id, cluster in enumerate(clusters):
        cluster["cluster_id"] = cluster_id

    best = clusters[0]
    return best["canonical_answer"], best["support_count"], clusters


def cluster_to_text(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return "No answer clusters yet."

    lines = []

    for c in clusters:
        cid = c.get("cluster_id")
        answer = c.get("canonical_answer")
        support = c.get("support_count")
        lines.append(f"Cluster {cid}: answer = {answer}, support = {support}")

        members = c.get("members", [])
        if members:
            lines.append(f"  members = {members}")

    return "\n".join(lines)