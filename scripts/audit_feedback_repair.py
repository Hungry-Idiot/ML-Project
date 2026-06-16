import argparse
import json
import re
from pathlib import Path
from collections import Counter, defaultdict


DEFAULT_JSONL = Path("outputs/feedback_repair_benchmark.jsonl")
DEFAULT_SUMMARY = Path("outputs/feedback_repair_benchmark_summary.json")
DEFAULT_OUT = Path("outputs/feedback_repair_audit.txt")


ANSWER_KEYS = [
    "final_answer",
    "candidate_answer",
    "selected_answer",
    "submitted_answer",
    "answer",
]


def read_jsonl(path):
    rows = []
    if not Path(path).exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path):
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def s(x):
    if x is None:
        return ""
    return str(x)


def one_line(x, limit=300):
    text = s(x).replace("\n", "\\n")
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def tail_text(x, limit=1000):
    text = s(x)
    if len(text) <= limit:
        return text
    return "...<tail>\n" + text[-limit:]


def usage_total(usage):
    if not isinstance(usage, dict):
        return 0
    if isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    total = 0
    for k in ["prompt_tokens", "completion_tokens", "reasoning_tokens"]:
        if isinstance(usage.get(k), int):
            total += usage[k]
    return total


def usage_brief(usage):
    if not isinstance(usage, dict):
        return "{}"
    return json.dumps({
        "prompt": usage.get("prompt_tokens"),
        "completion": usage.get("completion_tokens"),
        "total": usage.get("total_tokens"),
    }, ensure_ascii=False)


def extract_numbers(text):
    text = s(text)
    nums = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:/\d+)?(?![A-Za-z])", text)
    out = []
    for n in nums:
        if n not in out:
            out.append(n)
    return out[:20]


def raw_has_answer_marker(raw):
    raw = s(raw)
    patterns = [
        r'"final_answer"\s*:',
        r'"candidate_answer"\s*:',
        r'"selected_answer"\s*:',
        r'"answer"\s*:',
        r'FINAL_ANSWER\s*:',
        r'Final Answer\s*:',
        r'Answer\s*:',
        r'\\boxed\s*\{',
    ]
    return any(re.search(p, raw, flags=re.I) for p in patterns)


def raw_answer_markers(raw):
    raw = s(raw)
    markers = []
    checks = [
        ("json.final_answer", r'"final_answer"\s*:'),
        ("json.candidate_answer", r'"candidate_answer"\s*:'),
        ("json.selected_answer", r'"selected_answer"\s*:'),
        ("json.answer", r'"answer"\s*:'),
        ("FINAL_ANSWER", r'FINAL_ANSWER\s*:'),
        ("Final Answer", r'Final Answer\s*:'),
        ("Answer", r'Answer\s*:'),
        ("boxed", r'\\boxed\s*\{'),
    ]
    for name, pat in checks:
        if re.search(pat, raw, flags=re.I):
            markers.append(name)
    return markers


def parser_debug_brief(obj):
    dbg = obj.get("parser_debug") or {}
    return {
        "parsed_json": dbg.get("parsed_json"),
        "parsed_keys": dbg.get("parsed_keys"),
        "extracted_answer": dbg.get("extracted_answer"),
    }


def diagnostic_brief(diagnostic):
    if not isinstance(diagnostic, dict):
        return None

    return {
        "likely_error_type": diagnostic.get("likely_error_type"),
        "banned_assumption": diagnostic.get("banned_assumption"),
        "must_check": diagnostic.get("must_check"),
        "next_strategy_hint": diagnostic.get("next_strategy_hint"),
    }


def append_diagnostic(lines, prefix, diagnostic):
    brief = diagnostic_brief(diagnostic)
    if brief is None:
        return

    lines.append(f"{prefix}diagnostic.likely_error_type={brief.get('likely_error_type')}")
    lines.append(f"{prefix}diagnostic.banned_assumption={one_line(brief.get('banned_assumption'), 300)}")
    lines.append(f"{prefix}diagnostic.must_check={brief.get('must_check')}")
    lines.append(f"{prefix}diagnostic.next_strategy_hint={one_line(brief.get('next_strategy_hint'), 300)}")


def strict_equiv_brief(obj):
    details = obj.get("strict_equivalence") or {}
    if not isinstance(details, dict) or not details:
        return None
    return {
        "strict_equiv_result": details.get("strict_equiv_result"),
        "original_equiv_result": details.get("original_equiv_result"),
        "final_equiv_result": details.get("final_equiv_result"),
    }


def note_brief(note):
    if not isinstance(note, dict):
        return note
    return {
        "note_id": note.get("note_id"),
        "round": note.get("round"),
        "source": note.get("source"),
        "type": note.get("type"),
        "status": note.get("status"),
        "confidence": note.get("confidence"),
        "claim": one_line(note.get("claim"), 220),
        "supports_answer": note.get("supports_answer"),
        "blocks_answer": note.get("blocks_answer"),
        "metadata": note.get("metadata"),
    }


def admission_brief(result):
    if not isinstance(result, dict):
        return result
    note = result.get("note") or {}
    return {
        "note_id": note.get("note_id"),
        "type": note.get("type"),
        "claim": one_line(note.get("claim"), 220),
        "status": result.get("status"),
        "reason": one_line(result.get("reason"), 260),
        "duplicate_verified_note": result.get("duplicate_verified_note"),
        "api_call": result.get("api_call"),
    }


def is_invalid_like(obj, answer_key="answer"):
    if obj.get("invalid_answer") is True:
        return True
    if obj.get("invalid_selected_answer") is True:
        return True
    if obj.get(answer_key) in [None, ""]:
        return True
    return False


def get_attempts(record):
    main = record.get("main_agent") or {}
    return main.get("attempts") or []


def get_delm_rounds(record):
    delm = record.get("delm_lite") or {}
    return delm.get("rounds") or []


def summarize_records(records):
    out = []
    out.append("=== AUDIT SUMMARY ===")
    out.append(f"records: {len(records)}")

    main_solved = 0
    delm_solved = 0
    main_invalid = 0
    delm_invalid = 0
    main_duplicate = 0
    delm_duplicate = 0
    main_calls = 0
    delm_calls = 0
    main_tokens = 0
    delm_tokens = 0
    main_diagnostic_calls = 0
    delm_diagnostic_calls = 0
    main_diagnostic_tokens = 0
    delm_diagnostic_tokens = 0
    delm_verifier_calls = 0
    delm_verifier_tokens = 0
    delm_admission_calls = 0
    delm_admission_tokens = 0
    delm_admission_evaluations = 0
    delm_verified_notes_added = 0
    delm_rejected_notes = 0
    delm_uncertain_notes = 0
    delm_strict_prevented = 0
    delm_latent = 0

    flags = Counter()

    for r in records:
        main = r.get("main_agent") or {}
        delm = r.get("delm_lite") or {}

        if main.get("solved") is True:
            main_solved += 1
        if delm.get("solved") is True:
            delm_solved += 1
        if delm.get("latent_worker_solved") is True:
            delm_latent += 1

        for a in get_attempts(r):
            main_calls += 1
            main_tokens += usage_total(a.get("usage"))
            if a.get("invalid_answer") is True:
                main_invalid += 1
            if a.get("duplicate_forbidden_answer") is True:
                main_duplicate += 1
            diagnostic = a.get("diagnostic")
            if isinstance(diagnostic, dict):
                main_diagnostic_calls += int(diagnostic.get("api_call") is True)
                main_diagnostic_tokens += usage_total(diagnostic.get("usage"))
            if is_invalid_like(a, "answer") and raw_has_answer_marker(a.get("raw_output")):
                flags["main_possible_parser_false_negative"] += 1

        for rd in get_delm_rounds(r):
            for w in rd.get("workers") or []:
                delm_calls += 1
                delm_tokens += usage_total(w.get("usage"))
                if w.get("invalid_answer") is True:
                    delm_invalid += 1
                if w.get("duplicate_rejected_answer") is True:
                    delm_duplicate += 1
                if is_invalid_like(w, "answer") and raw_has_answer_marker(w.get("raw_output")):
                    flags["worker_possible_parser_false_negative"] += 1

            sel = rd.get("selector") or {}
            if sel:
                delm_calls += 1
                delm_tokens += usage_total(sel.get("usage"))
                if sel.get("invalid_selected_answer") is True or not sel.get("selected_answer"):
                    delm_invalid += 1
                if sel.get("selector_selected_rejected_answer") is True:
                    delm_duplicate += 1
                diagnostic = sel.get("diagnostic")
                if isinstance(diagnostic, dict):
                    delm_diagnostic_calls += int(diagnostic.get("api_call") is True)
                    delm_diagnostic_tokens += usage_total(diagnostic.get("usage"))
                for evaluation in sel.get("verifier_evaluations") or []:
                    if isinstance(evaluation, dict):
                        delm_verifier_calls += int(evaluation.get("api_call") is True)
                        delm_verifier_tokens += usage_total(evaluation.get("usage"))
                if not sel.get("selected_answer") and (rd.get("clusters") or []):
                    flags["selector_none_but_clusters_exist"] += 1
                if sel.get("selected_answer") and sel.get("reason"):
                    nums = extract_numbers(sel.get("reason"))
                    ans = s(sel.get("selected_answer"))
                    if nums and ans and ans not in nums:
                        flags["selector_reason_numbers_do_not_include_selected"] += 1

            note_admission = rd.get("note_admission") or {}
            delm_admission_evaluations += int(note_admission.get("admission_evaluations") or 0)
            delm_admission_calls += int(note_admission.get("admission_calls") or 0)
            delm_admission_tokens += int(note_admission.get("admission_tokens") or 0)
            delm_verified_notes_added += len(note_admission.get("verified_notes") or [])
            for result in note_admission.get("admission_results") or []:
                if result.get("status") == "rejected":
                    delm_rejected_notes += 1
                elif result.get("status") == "uncertain":
                    delm_uncertain_notes += 1
            for obj in list(rd.get("workers") or []) + [sel]:
                strict_details = obj.get("strict_equivalence") or {}
                if (
                    strict_details.get("original_equiv_result") is True
                    and strict_details.get("strict_equiv_result") is False
                    and strict_details.get("final_equiv_result") is False
                ):
                    delm_strict_prevented += 1

    out.append(f"main_solved: {main_solved}/{len(records)}")
    out.append(f"delm_solved: {delm_solved}/{len(records)}")
    out.append(f"delm_minus_main: {delm_solved - main_solved}")
    out.append(f"delm_latent_worker_solved: {delm_latent}/{len(records)}")
    out.append("")
    out.append(f"main_calls: {main_calls}")
    out.append(f"delm_calls: {delm_calls}")
    out.append(f"main_tokens_from_attempts: {main_tokens}")
    out.append(f"delm_tokens_from_rounds: {delm_tokens}")
    out.append(f"main_diagnostic_calls: {main_diagnostic_calls}")
    out.append(f"delm_diagnostic_calls: {delm_diagnostic_calls}")
    out.append(f"main_diagnostic_tokens: {main_diagnostic_tokens}")
    out.append(f"delm_diagnostic_tokens: {delm_diagnostic_tokens}")
    out.append(f"delm_verifier_calls: {delm_verifier_calls}")
    out.append(f"delm_verifier_tokens: {delm_verifier_tokens}")
    out.append(f"delm_admission_calls: {delm_admission_calls}")
    out.append(f"delm_admission_evaluations: {delm_admission_evaluations}")
    out.append(f"delm_admission_tokens: {delm_admission_tokens}")
    out.append(f"delm_verified_notes_added: {delm_verified_notes_added}")
    out.append(f"delm_rejected_notes: {delm_rejected_notes}")
    out.append(f"delm_uncertain_notes: {delm_uncertain_notes}")
    out.append(f"delm_strict_false_positives_prevented: {delm_strict_prevented}")
    out.append("")
    out.append(f"main_invalid_count: {main_invalid}")
    out.append(f"delm_invalid_count: {delm_invalid}")
    out.append(f"main_duplicate_count: {main_duplicate}")
    out.append(f"delm_duplicate_count: {delm_duplicate}")
    out.append("")
    out.append("flags:")
    if flags:
        for k, v in flags.most_common():
            out.append(f"- {k}: {v}")
    else:
        out.append("- none")

    return "\n".join(out)


def audit_main(record, lines, tail_limit):
    main = record.get("main_agent") or {}
    lines.append("")
    lines.append("## MAIN-AGENT")
    lines.append(f"solved={main.get('solved')} final_answer={one_line(main.get('final_answer'), 200)} rounds={main.get('rounds_used')} stop={main.get('stop_reason')}")
    lines.append(f"wrong_submitted={main.get('wrong_submitted_answers')}")
    lines.append(f"repeated_wrong={main.get('repeated_wrong_answer_count')} api_calls={main.get('api_calls')} usage={main.get('usage')} wall={main.get('wall_time_seconds')}")

    for a in get_attempts(record):
        lines.append("")
        lines.append(f"[MAIN round {a.get('round')}]")
        lines.append(f"answer={one_line(a.get('answer'), 200)} correct={a.get('correct')} invalid={a.get('invalid_answer')} duplicate={a.get('duplicate_forbidden_answer')}")
        lines.append(f"oracle_feedback={a.get('oracle_feedback')} finish_reason={a.get('finish_reason')} usage={usage_brief(a.get('usage'))}")
        strict_brief = strict_equiv_brief(a)
        if strict_brief is not None:
            lines.append(f"strict_equivalence={json.dumps(strict_brief, ensure_ascii=False)}")
        lines.append(f"parser_debug={parser_debug_brief(a)}")
        append_diagnostic(lines, "", a.get("diagnostic"))
        markers = raw_answer_markers(a.get("raw_output"))
        if markers:
            lines.append(f"raw_answer_markers={markers}")
        if is_invalid_like(a, "answer") or a.get("duplicate_forbidden_answer"):
            lines.append("raw_output_tail:")
            lines.append(tail_text(a.get("raw_output"), tail_limit))


def cluster_brief(cluster):
    return {
        "cluster_id": cluster.get("cluster_id"),
        "canonical_answer": cluster.get("canonical_answer"),
        "support_count": cluster.get("support_count"),
        "verified_support_count": cluster.get("verified_support_count"),
        "verified_block_count": cluster.get("verified_block_count"),
        "membership_values_verified": cluster.get("membership_values_verified"),
        "completeness_evidence_present": cluster.get("completeness_evidence_present"),
        "missing_verified_members": cluster.get("missing_verified_members"),
        "extra_unverified_members": cluster.get("extra_unverified_members"),
        "set_support_type": cluster.get("set_support_type"),
        "supporting_note_ids": cluster.get("supporting_note_ids"),
        "blocking_note_ids": cluster.get("blocking_note_ids"),
        "members": cluster.get("members"),
    }


def audit_delm(record, lines, tail_limit):
    delm = record.get("delm_lite") or {}
    lines.append("")
    lines.append("## DELM-LITE")
    lines.append(f"solved={delm.get('solved')} final_answer={one_line(delm.get('final_answer'), 200)} rounds={delm.get('rounds_used')} stop={delm.get('stop_reason')} latent={delm.get('latent_worker_solved')}")
    lines.append(f"wrong_submitted={delm.get('wrong_submitted_answers')}")
    lines.append(f"repeated_wrong={delm.get('repeated_wrong_answer_count')} api_calls={delm.get('api_calls')} usage={delm.get('usage')} wall={delm.get('wall_time_seconds')}")
    final_context = delm.get("final_shared_context") or {}
    verified_notes = final_context.get("verified_notes") or []
    rejected_notes = final_context.get("rejected_notes") or []
    lines.append(f"final_verified_notes_count={len(verified_notes)} final_rejected_or_uncertain_notes_count={len(rejected_notes)}")
    if verified_notes:
        lines.append("final_verified_notes:")
        for note in verified_notes[-12:]:
            lines.append(f"- {json.dumps(note_brief(note), ensure_ascii=False)}")
    if rejected_notes:
        lines.append("final_rejected_or_uncertain_notes_tail:")
        for note in rejected_notes[-12:]:
            lines.append(f"- {json.dumps(note_brief(note), ensure_ascii=False)}")

    for rd in get_delm_rounds(record):
        lines.append("")
        lines.append(f"[DELM round {rd.get('round')}] submitted={one_line(rd.get('submitted_answer'), 200)} correct={rd.get('correct')}")
        context_before = rd.get("context_before") or {}
        rejected = context_before.get("rejected_answers") or []
        lines.append(f"context_before.rejected_answers={rejected}")
        lines.append(f"context_before.diagnostics={context_before.get('diagnostics') or []}")
        lines.append(f"context_before.banned_assumptions={context_before.get('banned_assumptions') or []}")
        lines.append(f"context_before.must_check_items={context_before.get('must_check_items') or []}")
        lines.append(f"context_before.strategy_hints={context_before.get('strategy_hints') or []}")
        lines.append(f"context_before.verified_notes_count={len(context_before.get('verified_notes') or [])}")
        if context_before.get("verified_notes"):
            for note in (context_before.get("verified_notes") or [])[-8:]:
                lines.append(f"context_before.verified_note={json.dumps(note_brief(note), ensure_ascii=False)}")

        workers = rd.get("workers") or []
        for w in workers:
            lines.append("")
            lines.append(f"  [worker {w.get('worker_id')}] role={w.get('role')}")
            lines.append(f"  answer={one_line(w.get('answer'), 200)} correct={w.get('correct')} invalid={w.get('invalid_answer')} duplicate_rejected={w.get('duplicate_rejected_answer')}")
            lines.append(f"  finish_reason={w.get('finish_reason')} usage={usage_brief(w.get('usage'))}")
            strict_brief = strict_equiv_brief(w)
            if strict_brief is not None:
                lines.append(f"  strict_equivalence={json.dumps(strict_brief, ensure_ascii=False)}")
            lines.append(f"  parser_debug={parser_debug_brief(w)}")
            parsed = w.get("parsed") or {}
            if parsed:
                lines.append(f"  parsed.confidence={parsed.get('confidence')} parsed.strategy={one_line(parsed.get('strategy'), 300)}")
                lines.append(f"  parsed.reason={one_line(parsed.get('reason'), 500)}")
            claims = w.get("intermediate_claims") or parsed.get("intermediate_claims") or []
            if claims:
                lines.append("  intermediate_claims:")
                for claim in claims[:5]:
                    lines.append(f"  - {json.dumps(claim, ensure_ascii=False)}")
            admissions = w.get("admission_results") or []
            if admissions:
                lines.append("  admission_results:")
                for result in admissions:
                    lines.append(f"  - {json.dumps(admission_brief(result), ensure_ascii=False)}")
            markers = raw_answer_markers(w.get("raw_output"))
            if markers:
                lines.append(f"  raw_answer_markers={markers}")
            if is_invalid_like(w, "answer") or w.get("duplicate_rejected_answer"):
                lines.append("  raw_output_tail:")
                lines.append(tail_text(w.get("raw_output"), tail_limit))

        note_admission = rd.get("note_admission") or {}
        if note_admission:
            lines.append("")
            lines.append(f"  note_admission.verified_added={len(note_admission.get('verified_notes') or [])} rejected_or_uncertain={len(note_admission.get('rejected_notes') or [])} evaluations={note_admission.get('admission_evaluations')} calls={note_admission.get('admission_calls')} tokens={note_admission.get('admission_tokens')}")
            for note in note_admission.get("verified_notes") or []:
                lines.append(f"  verified_added={json.dumps(note_brief(note), ensure_ascii=False)}")
            for result in note_admission.get("admission_results") or []:
                lines.append(f"  admission={json.dumps(admission_brief(result), ensure_ascii=False)}")

        clusters = rd.get("clusters") or []
        lines.append("")
        lines.append(f"  clusters_count={len(clusters)}")
        for c in clusters[:8]:
            lines.append(f"  cluster={json.dumps(cluster_brief(c), ensure_ascii=False)}")
        if len(clusters) > 8:
            lines.append(f"  ... {len(clusters) - 8} more clusters omitted")

        sel = rd.get("selector") or {}
        lines.append("")
        lines.append("  [selector]")
        lines.append(f"  selected_answer={one_line(sel.get('selected_answer'), 200)} original_selected={one_line(sel.get('original_selected_answer'), 200)} selected_cluster_id={sel.get('selected_cluster_id')}")
        lines.append(f"  selector_mode={sel.get('selector_mode')} selected_verifier_score={sel.get('selected_verifier_score')} selected_verifier_verdict={sel.get('selected_verifier_verdict')} all_verifier_rejected={sel.get('all_verifier_rejected')}")
        lines.append(f"  verified_support_count={sel.get('verified_support_count')} verified_block_count={sel.get('verified_block_count')} supporting_note_ids={sel.get('supporting_note_ids')} blocking_note_ids={sel.get('blocking_note_ids')}")
        lines.append(f"  membership_values_verified={sel.get('membership_values_verified')} completeness_evidence_present={sel.get('completeness_evidence_present')} missing_verified_members={sel.get('missing_verified_members')} extra_unverified_members={sel.get('extra_unverified_members')} set_support_type={sel.get('set_support_type')}")
        lines.append(f"  final_selection_score={json.dumps(sel.get('final_selection_score'), ensure_ascii=False)}")
        lines.append(f"  correct={sel.get('correct')} invalid_selected={sel.get('invalid_selected_answer')} selected_rejected={sel.get('selector_selected_rejected_answer')} fallback={sel.get('fallback_selected_non_rejected')}")
        strict_brief = strict_equiv_brief(sel)
        if strict_brief is not None:
            lines.append(f"  strict_equivalence={json.dumps(strict_brief, ensure_ascii=False)}")
        lines.append(f"  finish_reason={sel.get('finish_reason')} usage={usage_brief(sel.get('usage'))}")
        lines.append(f"  reason={one_line(sel.get('reason') or ((sel.get('parsed') or {}).get('reason')), 700)}")
        append_diagnostic(lines, "  ", sel.get("diagnostic"))
        selector_cluster_scores = sel.get("cluster_scores") or []
        if selector_cluster_scores:
            lines.append("  selector_cluster_scores:")
            for score in selector_cluster_scores[:8]:
                brief = {
                    "cluster_id": score.get("cluster_id"),
                    "canonical_answer": score.get("canonical_answer"),
                    "support_count": score.get("support_count"),
                    "avg_confidence": score.get("avg_confidence"),
                    "max_confidence": score.get("max_confidence"),
                    "verified_support_count": score.get("verified_support_count"),
                    "verified_block_count": score.get("verified_block_count"),
                    "membership_values_verified": score.get("membership_values_verified"),
                    "completeness_evidence_present": score.get("completeness_evidence_present"),
                    "missing_verified_members": score.get("missing_verified_members"),
                    "extra_unverified_members": score.get("extra_unverified_members"),
                    "set_support_type": score.get("set_support_type"),
                    "verifier_score": score.get("verifier_score"),
                    "adjusted_verifier_score": score.get("adjusted_verifier_score"),
                    "unsupported_verifier_accept": score.get("unsupported_verifier_accept"),
                    "supporting_note_ids": score.get("supporting_note_ids"),
                    "blocking_note_ids": score.get("blocking_note_ids"),
                    "final_selection_score": score.get("final_selection_score"),
                }
                lines.append(f"  - {json.dumps(brief, ensure_ascii=False)}")
        verifier_evaluations = sel.get("verifier_evaluations") or []
        if verifier_evaluations:
            lines.append("  verifier_evaluations:")
            for evaluation in verifier_evaluations:
                if not isinstance(evaluation, dict):
                    continue
                brief = {
                    "cluster_id": evaluation.get("cluster_id"),
                    "candidate_answer": evaluation.get("candidate_answer"),
                    "support_count": evaluation.get("support_count"),
                    "avg_confidence": evaluation.get("avg_confidence"),
                    "max_confidence": evaluation.get("max_confidence"),
                    "member_worker_ids": evaluation.get("member_worker_ids"),
                    "verified_support_count": evaluation.get("verified_support_count"),
                    "verified_block_count": evaluation.get("verified_block_count"),
                    "supporting_note_ids": evaluation.get("supporting_note_ids"),
                    "blocking_note_ids": evaluation.get("blocking_note_ids"),
                    "membership_values_verified": evaluation.get("membership_values_verified"),
                    "completeness_evidence_present": evaluation.get("completeness_evidence_present"),
                    "missing_verified_members": evaluation.get("missing_verified_members"),
                    "extra_unverified_members": evaluation.get("extra_unverified_members"),
                    "set_support_type": evaluation.get("set_support_type"),
                    "verdict": evaluation.get("verdict"),
                    "score": evaluation.get("score"),
                    "reason": evaluation.get("reason"),
                    "violated_rejected_answer": evaluation.get("violated_rejected_answer"),
                    "uses_banned_assumption": evaluation.get("uses_banned_assumption"),
                    "addresses_must_check": evaluation.get("addresses_must_check"),
                }
                lines.append(f"  - {json.dumps(brief, ensure_ascii=False)}")
        nums = extract_numbers(sel.get("reason") or ((sel.get("parsed") or {}).get("reason")))
        if nums:
            lines.append(f"  reason_numbers={nums}")
        if sel.get("selected_answer") and nums and s(sel.get("selected_answer")) not in nums:
            lines.append("  FLAG: selector reason contains numbers but not the selected answer.")
        if (not sel.get("selected_answer")) and clusters:
            lines.append("  FLAG: selector selected None even though clusters exist.")
        if sel.get("raw_output"):
            markers = raw_answer_markers(sel.get("raw_output"))
            if markers:
                lines.append(f"  raw_answer_markers={markers}")
        if sel.get("invalid_selected_answer") or not sel.get("selected_answer"):
            lines.append("  raw_output_tail:")
            lines.append(tail_text(sel.get("raw_output"), tail_limit))


def audit_case(record, tail_limit):
    lines = []
    lines.append("")
    lines.append("=" * 120)
    lines.append(f"CASE id={record.get('id')} qid={record.get('question_id')} type={record.get('answer_type')}")
    lines.append(f"gold={one_line(record.get('gold'), 300)}")
    lines.append(f"raw_selected_answer={one_line(record.get('raw_selected_answer'), 200)} raw_support={record.get('raw_selected_support')} raw_correct={record.get('raw_correct')}")
    lines.append(f"oracle_correct={record.get('oracle_correct')}")
    settings = record.get("settings") or {}
    if settings:
        lines.append(f"settings={json.dumps(settings, ensure_ascii=False)}")

    audit_main(record, lines, tail_limit)
    audit_delm(record, lines, tail_limit)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_JSONL))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--tail", type=int, default=1200)
    parser.add_argument("--case-ids", default="")
    args = parser.parse_args()

    records = read_jsonl(args.input)

    if args.case_ids.strip():
        ids = {int(x.strip()) for x in args.case_ids.split(",") if x.strip()}
        records = [r for r in records if int(r.get("id")) in ids]

    records = sorted(records, key=lambda r: int(r.get("id")))

    lines = []
    lines.append(f"audit_input={args.input}")
    lines.append(f"audit_summary={args.summary}")
    lines.append(f"records_loaded={len(records)}")

    summary = load_json(args.summary)
    if summary is not None:
        lines.append("")
        lines.append("=== RAW SUMMARY JSON TOP-LEVEL ===")
        try:
            compact = {
                "environment": summary.get("environment"),
                "total": ((summary.get("summary") or {}).get("total")),
                "main_agent": ((summary.get("summary") or {}).get("main_agent")),
                "delm_lite": ((summary.get("summary") or {}).get("delm_lite")),
                "delm_minus_main_solved": ((summary.get("summary") or {}).get("delm_minus_main_solved")),
            }
            lines.append(json.dumps(compact, ensure_ascii=False, indent=2))
        except Exception as e:
            lines.append(f"failed_to_render_summary: {e}")

    lines.append("")
    lines.append(summarize_records(records))

    for record in records:
        lines.append(audit_case(record, args.tail))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote audit report to {out_path}")
    print(f"Records audited: {len(records)}")


if __name__ == "__main__":
    main()
