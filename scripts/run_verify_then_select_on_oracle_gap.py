import os
import re
import sys
import json
import time
from pathlib import Path
from typing import Any
from collections import Counter, defaultdict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.utils import (
    get_client,
    extract_boxed,
    safe_verify,
    equivalent,
)


INPUT_PATH = Path("outputs/selector_failure_cases.jsonl")
OUT_PATH = Path("outputs/verify_then_select_on_oracle_gap.jsonl")
ERROR_PATH = Path("outputs/verify_then_select_on_oracle_gap_api_errors.jsonl")
OUT_MD = Path("outputs/verify_then_select_on_oracle_gap_report.md")

MAX_TOKENS = int(os.getenv("VTS_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("VTS_TEMPERATURE", "0.2"))
SLEEP_SECONDS = float(os.getenv("VTS_SLEEP", "0.5"))

# 调试用：VTS_LIMIT=1 先跑 1 题。
LIMIT = int(os.getenv("VTS_LIMIT", "0"))

# 每个 sample reasoning tail 太长会浪费 token。
TAIL_CHARS = int(os.getenv("VTS_TAIL_CHARS", "1200"))

# 每个 candidate cluster 调几次 verifier。默认 1 次；如果想更稳，可以设为 2 或 3。
VERIFIER_REPEATS = int(os.getenv("VTS_VERIFIER_REPEATS", "1"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    return records


def write_jsonl_append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def load_done_ids(path: Path) -> set[int]:
    return {int(ex["id"]) for ex in read_jsonl(path) if "id" in ex}


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


def short_text(x: Any, max_len: int = 160) -> str:
    if x is None:
        return ""

    s = str(x).replace("\n", " ").strip()

    if len(s) <= max_len:
        return s

    return s[:max_len] + "..."


def tail_text(x: Any, max_len: int) -> str:
    if x is None:
        return ""

    s = str(x).strip()

    if len(s) <= max_len:
        return s

    return s[-max_len:]


def pct(x: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{x / total:.2%}"


def safe_int(x: Any, default: int | None = None) -> int | None:
    try:
        return int(x)
    except Exception:
        return default


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """
    尽量从模型输出中解析 JSON。
    支持：
    - 纯 JSON
    - ```json ... ```
    - 前后有解释文字，中间包含 {...}
    """
    if not text:
        return None

    s = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, flags=re.S | re.I)
    if fence_match:
        s2 = fence_match.group(1).strip()
        try:
            return json.loads(s2)
        except Exception:
            pass

    try:
        return json.loads(s)
    except Exception:
        pass

    start = s.find("{")
    end = s.rfind("}")

    if start != -1 and end != -1 and end > start:
        candidate = s[start:end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None

    return None


def verdict_to_score(verdict: str | None, confidence: float) -> float:
    """
    用于 rule-based selector 的辅助分数。
    """
    verdict = (verdict or "").lower().strip()
    confidence = max(0.0, min(100.0, confidence))

    if verdict == "accept":
        return 1000.0 + confidence
    if verdict == "uncertain":
        return 500.0 + confidence
    if verdict == "reject":
        return 0.0 + confidence

    return 250.0 + confidence


def build_cluster_support_text(case: dict[str, Any], cluster: dict[str, Any]) -> str:
    """
    给 verifier 看某个 cluster 的支持样本，包括 sample answer 和 reasoning tail。
    """
    sample_tails = case.get("sample_output_tails", [])
    sc3_pred_answers = case.get("sc3_pred_answers", [])

    lines = []
    members = cluster.get("members", [])

    if not members:
        lines.append("No supporting member samples are available.")
        return "\n".join(lines)

    for member in members:
        sample_id = safe_int(member.get("sample_id"), None)
        member_answer = member.get("answer")

        lines.append(f"Sample {sample_id}")
        lines.append(f"Predicted answer: {member_answer}")

        if sample_id is not None and 0 <= sample_id < len(sc3_pred_answers):
            lines.append(f"Original SC3 answer at this sample: {sc3_pred_answers[sample_id]}")

        if sample_id is not None and 0 <= sample_id < len(sample_tails):
            tail = tail_text(sample_tails[sample_id], TAIL_CHARS)
            lines.append("Reasoning/output tail:")
            lines.append(tail)
        else:
            lines.append("Reasoning/output tail: unavailable.")

        lines.append("")

    return "\n".join(lines).strip()


def build_verifier_prompt(case: dict[str, Any], cluster: dict[str, Any], repeat_id: int) -> str:
    problem = case.get("problem", "")
    candidate_answer = cluster.get("canonical_answer")
    support_count = cluster.get("support_count")
    cluster_id = cluster.get("cluster_id")
    support_text = build_cluster_support_text(case, cluster)

    return f"""
You are a rigorous verifier for a very hard olympiad-style math problem.

Your task is to verify ONE candidate answer cluster.

Important rules:
- Do not trust the support count blindly.
- Check the mathematical reasoning and the final answer.
- If the reasoning relies mainly on "known result" without proof, be cautious.
- If the reasoning contains an off-by-one error, boundary mistake, unjustified extremal claim, or invalid construction, point it out.
- You may do your own verification, but focus on whether this candidate answer is reliable.
- Return ONLY a JSON object. Do not write markdown.

JSON format:
{{
  "cluster_id": {cluster_id},
  "candidate_answer": "{candidate_answer}",
  "verdict": "accept" | "reject" | "uncertain",
  "confidence": 0-100,
  "detected_flaw": "briefly describe the main flaw, or empty string if none",
  "rationale": "brief but concrete verification rationale",
  "final_answer_if_this_cluster_is_correct": "{candidate_answer}"
}}

Problem:
{problem}

Candidate cluster:
Cluster ID: {cluster_id}
Candidate answer: {candidate_answer}
Support count: {support_count}

Supporting sample reasoning:
{support_text}

Verifier repeat id: {repeat_id}
"""


def build_selector_prompt(
    case: dict[str, Any],
    clusters: list[dict[str, Any]],
    verifier_notes: list[dict[str, Any]],
) -> str:
    problem = case.get("problem", "")
    gold_hidden_warning = "The gold answer is NOT provided. You must choose only from candidate clusters."

    cluster_lines = []
    for c in clusters:
        cluster_lines.append(
            f"Cluster {c.get('cluster_id')}: "
            f"answer={c.get('canonical_answer')}, "
            f"support={c.get('support_count')}, "
            f"members={c.get('members')}"
        )

    note_lines = []
    for note in verifier_notes:
        parsed = note.get("parsed", {}) or {}
        note_lines.append(
            json.dumps(
                {
                    "cluster_id": note.get("cluster_id"),
                    "repeat_id": note.get("repeat_id"),
                    "candidate_answer": note.get("candidate_answer"),
                    "verdict": parsed.get("verdict"),
                    "confidence": parsed.get("confidence"),
                    "detected_flaw": parsed.get("detected_flaw"),
                    "rationale": parsed.get("rationale"),
                },
                ensure_ascii=False,
            )
        )

    return f"""
You are a final selector agent for a hard olympiad-style math problem.

{gold_hidden_warning}

You are given:
1. The original problem.
2. Candidate answer clusters.
3. Independent verifier notes for each cluster.

Your task:
- Choose exactly one existing cluster.
- Do not invent a new answer.
- Do not choose by support count alone.
- Prefer clusters whose verifier notes contain concrete mathematical verification.
- Be skeptical of clusters whose notes mention unjustified known results, off-by-one mistakes, weak lower bounds, or invalid constructions.

Output format:
Selected Cluster: <cluster_id>
Final Answer: \\boxed{{answer_from_that_cluster}}

Problem:
{problem}

Candidate clusters:
{chr(10).join(cluster_lines)}

Verifier notes:
{chr(10).join(note_lines)}
"""


def call_llm(client, prompt: str) -> dict[str, Any]:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

        choice = resp.choices[0]
        content = choice.message.content or ""

        return {
            "content": content,
            "finish_reason": choice.finish_reason,
            "usage": response_usage_to_dict(getattr(resp, "usage", None)),
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
        m = re.search(pattern, text, flags=re.I)
        if m:
            return safe_int(m.group(1), None)

    return None


def find_cluster_by_answer(answer: str | None, clusters: list[dict[str, Any]]) -> int | None:
    answer = normalize_answer(answer)

    if answer is None:
        return None

    for c in clusters:
        candidate = normalize_answer(c.get("canonical_answer"))
        if candidate is not None and equivalent(candidate, answer):
            return safe_int(c.get("cluster_id"), None)

    return None


def choose_by_rule_based_verifier(
    clusters: list[dict[str, Any]],
    verifier_notes: list[dict[str, Any]],
) -> tuple[int | None, str | None, float]:
    """
    不用 LLM selector，直接根据 verifier verdict/confidence 做一个透明的 rule-based selector。
    这样可以帮助判断：失败到底来自 verifier，还是来自 selector。
    """
    if not clusters:
        return None, None, 0.0

    scores: dict[int, list[float]] = defaultdict(list)

    for note in verifier_notes:
        cid = safe_int(note.get("cluster_id"), None)
        parsed = note.get("parsed", {}) or {}
        verdict = parsed.get("verdict")
        confidence = safe_float(parsed.get("confidence"), 0.0)

        if cid is not None:
            scores[cid].append(verdict_to_score(verdict, confidence))

    best_cluster = None
    best_score = -1.0

    for c in clusters:
        cid = safe_int(c.get("cluster_id"), None)
        if cid is None:
            continue

        if scores.get(cid):
            avg_score = sum(scores[cid]) / len(scores[cid])
        else:
            avg_score = 0.0

        # support_count 只作为很小的 tie-breaker，避免重新退化为多数投票。
        avg_score += 0.01 * safe_float(c.get("support_count"), 0.0)

        if avg_score > best_score:
            best_score = avg_score
            best_cluster = c

    if best_cluster is None:
        return None, None, 0.0

    return (
        safe_int(best_cluster.get("cluster_id"), None),
        normalize_answer(best_cluster.get("canonical_answer")),
        best_score,
    )


def get_cluster_by_id(clusters: list[dict[str, Any]], cid: int | None) -> dict[str, Any] | None:
    if cid is None:
        return None

    for c in clusters:
        if safe_int(c.get("cluster_id"), None) == cid:
            return c

    return None


def make_md_report(records: list[dict[str, Any]]) -> str:
    lines = []
    lines.append("# Verify-then-Select on Oracle-gap Cases")
    lines.append("")
    lines.append(f"- Input: `{INPUT_PATH}`")
    lines.append(f"- Total cases: **{len(records)}**")
    lines.append("")

    rows = []
    for r in records:
        rows.append([
            r.get("id"),
            r.get("question_id"),
            r.get("answer_type"),
            short_text(r.get("gold"), 80),
            short_text(r.get("raw_selected_answer"), 80),
            short_text(r.get("previous_selector_selected_answer"), 80),
            short_text(r.get("vts_selected_answer"), 80),
            r.get("vts_correct"),
            short_text(r.get("rule_selected_answer"), 80),
            r.get("rule_correct"),
        ])

    lines.append("| id | qid | type | gold | RawVote | Old Selector | VTS Selector | VTS Correct | Rule Selector | Rule Correct |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in row) + " |")

    lines.append("")

    for r in records:
        lines.append(f"## Case id={r.get('id')}, question_id={r.get('question_id')}")
        lines.append("")
        lines.append(f"- Gold: `{short_text(r.get('gold'), 200)}`")
        lines.append(f"- RawVote selected: `{short_text(r.get('raw_selected_answer'), 200)}`")
        lines.append(f"- Previous selector selected: `{short_text(r.get('previous_selector_selected_answer'), 200)}`")
        lines.append(f"- VTS selected: `{short_text(r.get('vts_selected_answer'), 200)}`, correct=`{r.get('vts_correct')}`")
        lines.append(f"- Rule selected: `{short_text(r.get('rule_selected_answer'), 200)}`, correct=`{r.get('rule_correct')}`")
        lines.append("")

        lines.append("### Candidate clusters")
        lines.append("")
        lines.append("| cluster_id | support | answer | members |")
        lines.append("|---|---|---|---|")
        for c in r.get("clusters", []):
            answer_text = short_text(c.get("canonical_answer"), 200).replace("|", "\\|")
            members_text = short_text(c.get("members"), 400).replace("|", "\\|")

            lines.append(
                f"| {c.get('cluster_id')} | {c.get('support_count')} | "
                f"{answer_text} | "
                f"{members_text} |"
            )
        lines.append("")

        lines.append("### Verifier notes")
        lines.append("")
        for note in r.get("verifier_notes", []):
            parsed = note.get("parsed", {}) or {}
            lines.append(
                f"- cluster={note.get('cluster_id')}, repeat={note.get('repeat_id')}, "
                f"verdict={parsed.get('verdict')}, confidence={parsed.get('confidence')}"
            )
            lines.append(f"  - flaw: {parsed.get('detected_flaw')}")
            lines.append(f"  - rationale: {parsed.get('rationale')}")
        lines.append("")

        lines.append("### VTS selector output")
        lines.append("")
        lines.append("```text")
        lines.append(r.get("vts_selector_raw_output", ""))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Missing {INPUT_PATH}\n"
            "Please run scripts/inspect_selector_failure_cases.py first."
        )

    cases = read_jsonl(INPUT_PATH)
    cases.sort(key=lambda x: int(x["id"]))

    if LIMIT > 0:
        cases = cases[:LIMIT]

    client = get_client()
    done_ids = load_done_ids(OUT_PATH)

    print("Input:", INPUT_PATH)
    print("Output:", OUT_PATH)
    print("Error log:", ERROR_PATH)
    print("Report:", OUT_MD)
    print("Cases:", len(cases))
    print("Already done:", len(done_ids))
    print("Max tokens:", MAX_TOKENS)
    print("Temperature:", TEMPERATURE)
    print("Verifier repeats:", VERIFIER_REPEATS)
    print("Limit:", LIMIT if LIMIT > 0 else "None")

    for n, case in enumerate(cases, start=1):
        idx = int(case["id"])

        if idx in done_ids:
            continue

        print(f"\n===== Verify-then-Select Case {n}/{len(cases)}, id={idx}, qid={case.get('question_id')} =====")

        clusters = case.get("clusters", [])
        if not clusters:
            record = {
                "id": idx,
                "question_id": case.get("question_id"),
                "answer_type": case.get("answer_type"),
                "gold": case.get("gold"),
                "error": "no_clusters",
                "correct": False,
            }
            write_jsonl_append(OUT_PATH, record)
            continue

        verifier_notes = []
        had_api_error = False

        for cluster in clusters:
            cid = cluster.get("cluster_id")
            candidate_answer = cluster.get("canonical_answer")

            for repeat_id in range(VERIFIER_REPEATS):
                print(f"\n--- Verifying cluster {cid}, answer={candidate_answer}, repeat={repeat_id} ---")

                prompt = build_verifier_prompt(case, cluster, repeat_id)
                result = call_llm(client, prompt)

                if result.get("error") is not None or result.get("finish_reason") == "api_error":
                    had_api_error = True

                parsed = extract_json_object(result.get("content"))

                note = {
                    "cluster_id": cid,
                    "candidate_answer": candidate_answer,
                    "support_count": cluster.get("support_count"),
                    "repeat_id": repeat_id,
                    "raw_output": result.get("content", ""),
                    "finish_reason": result.get("finish_reason"),
                    "usage": result.get("usage"),
                    "error": result.get("error"),
                    "parsed": parsed,
                }

                verifier_notes.append(note)

                if parsed:
                    print("verdict:", parsed.get("verdict"))
                    print("confidence:", parsed.get("confidence"))
                    print("flaw:", short_text(parsed.get("detected_flaw"), 160))
                else:
                    print("parsed: None")
                    print("raw:", short_text(result.get("content"), 200))

                time.sleep(SLEEP_SECONDS)

        if had_api_error:
            error_record = {
                "id": idx,
                "question_id": case.get("question_id"),
                "answer_type": case.get("answer_type"),
                "gold": case.get("gold"),
                "clusters": clusters,
                "verifier_notes": verifier_notes,
                "note": "Skipped because at least one verifier call had api_error.",
            }
            write_jsonl_append(ERROR_PATH, error_record)
            print("[SKIP] API error occurred. This case was not saved to main output.")
            continue

        print("\n--- Rule-based selection from verifier notes ---")
        rule_cluster_id, rule_answer, rule_score = choose_by_rule_based_verifier(clusters, verifier_notes)
        rule_correct = safe_verify(case.get("gold"), rule_answer)
        print("rule_cluster_id:", rule_cluster_id)
        print("rule_answer:", rule_answer)
        print("rule_score:", rule_score)
        print("rule_correct:", rule_correct)

        print("\n--- LLM final selector ---")
        selector_prompt = build_selector_prompt(case, clusters, verifier_notes)
        selector_result = call_llm(client, selector_prompt)

        if selector_result.get("error") is not None or selector_result.get("finish_reason") == "api_error":
            error_record = {
                "id": idx,
                "question_id": case.get("question_id"),
                "answer_type": case.get("answer_type"),
                "gold": case.get("gold"),
                "clusters": clusters,
                "verifier_notes": verifier_notes,
                "selector_result": selector_result,
                "note": "Skipped because selector call had api_error.",
            }
            write_jsonl_append(ERROR_PATH, error_record)
            print("[SKIP] Selector API error occurred. This case was not saved to main output.")
            continue

        selector_output = selector_result.get("content", "")
        selected_cluster_id = parse_selected_cluster_id(selector_output)
        parsed_answer = normalize_answer(extract_boxed(selector_output))

        used_fallback = False

        if selected_cluster_id is not None and get_cluster_by_id(clusters, selected_cluster_id) is not None:
            selected_cluster = get_cluster_by_id(clusters, selected_cluster_id)
            selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
        else:
            matched_id = find_cluster_by_answer(parsed_answer, clusters)
            if matched_id is not None:
                selected_cluster_id = matched_id
                selected_cluster = get_cluster_by_id(clusters, selected_cluster_id)
                selected_answer = normalize_answer(selected_cluster.get("canonical_answer"))
            else:
                # 兜底：使用 rule-based verifier 的选择，而不是 support 最大的选择。
                selected_cluster_id = rule_cluster_id
                selected_answer = rule_answer
                used_fallback = True

        vts_correct = safe_verify(case.get("gold"), selected_answer)

        record = {
            "id": idx,
            "question_id": case.get("question_id"),
            "answer_type": case.get("answer_type"),
            "problem": case.get("problem"),
            "gold": case.get("gold"),

            "method": "DELM-lite-Verify-then-Select-on-OracleGap",

            "single_pred_answer": case.get("single_pred_answer"),
            "single_correct": case.get("single_correct"),

            "sc3_pred_answers": case.get("sc3_pred_answers"),
            "sample_correct_flags": case.get("sample_correct_flags"),
            "correct_sample_ids": case.get("correct_sample_ids"),

            "raw_selected_answer": case.get("raw_selected_answer"),
            "raw_correct": case.get("raw_correct"),
            "raw_selected_support": case.get("raw_selected_support"),

            "previous_selector_selected_answer": case.get("selector_selected_answer"),
            "previous_selector_correct": case.get("selector_correct"),
            "previous_selector_selected_cluster_id": case.get("selector_selected_cluster_id"),

            "clusters": clusters,
            "verifier_notes": verifier_notes,

            "rule_selected_cluster_id": rule_cluster_id,
            "rule_selected_answer": rule_answer,
            "rule_score": rule_score,
            "rule_correct": rule_correct,

            "vts_selector_raw_output": selector_output,
            "vts_selector_finish_reason": selector_result.get("finish_reason"),
            "vts_selector_usage": selector_result.get("usage"),
            "vts_selector_error": selector_result.get("error"),

            "vts_selected_cluster_id": selected_cluster_id,
            "vts_selected_answer": selected_answer,
            "selected_answer": selected_answer,
            "pred_answer": selected_answer,
            "vts_correct": vts_correct,
            "correct": vts_correct,

            "used_fallback": used_fallback,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "verifier_repeats": VERIFIER_REPEATS,
        }

        write_jsonl_append(OUT_PATH, record)

        print("gold:", case.get("gold"))
        print("raw_selected_answer:", case.get("raw_selected_answer"))
        print("old_selector_answer:", case.get("selector_selected_answer"))
        print("vts_selected_cluster_id:", selected_cluster_id)
        print("vts_selected_answer:", selected_answer)
        print("vts_correct:", vts_correct)
        print("used_fallback:", used_fallback)

        time.sleep(SLEEP_SECONDS)

    final_records = read_jsonl(OUT_PATH)
    final_records.sort(key=lambda x: int(x["id"]))

    total = len(final_records)
    raw_correct = sum(1 for x in final_records if x.get("raw_correct") is True)
    old_selector_correct = sum(1 for x in final_records if x.get("previous_selector_correct") is True)
    rule_correct = sum(1 for x in final_records if x.get("rule_correct") is True)
    vts_correct = sum(1 for x in final_records if x.get("vts_correct") is True)

    recovered_over_raw = sum(
        1 for x in final_records
        if x.get("vts_correct") is True and x.get("raw_correct") is not True
    )
    recovered_over_old_selector = sum(
        1 for x in final_records
        if x.get("vts_correct") is True and x.get("previous_selector_correct") is not True
    )

    fallback_count = sum(1 for x in final_records if x.get("used_fallback") is True)

    print("\n=== Verify-then-Select on Oracle-gap Results ===")
    print("File:", OUT_PATH)
    print("Total:", total)
    print("RawVote correct:", raw_correct, pct(raw_correct, total))
    print("Old selector correct:", old_selector_correct, pct(old_selector_correct, total))
    print("Rule-based verifier selector correct:", rule_correct, pct(rule_correct, total))
    print("VTS selector correct:", vts_correct, pct(vts_correct, total))
    print("Recovered over RawVote:", recovered_over_raw)
    print("Recovered over old Selector:", recovered_over_old_selector)
    print("Fallback count:", fallback_count)

    cluster_counter = Counter(x.get("vts_selected_cluster_id") for x in final_records)
    print("\n=== selected_cluster_id distribution ===")
    for k, v in sorted(cluster_counter.items(), key=lambda x: str(x[0])):
        print(f"{k}: {v}")

    OUT_MD.write_text(make_md_report(final_records), encoding="utf-8")

    print("\nSaved:")
    print("-", OUT_PATH)
    print("-", ERROR_PATH)
    print("-", OUT_MD)


if __name__ == "__main__":
    main()