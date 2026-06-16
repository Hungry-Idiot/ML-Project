import hashlib
import json
import re
import time
from typing import Any

from scripts.math_note_tools import (
    check_equation_claim,
    check_strict_equiv_function_claim,
    extract_membership_values_from_claim,
    numeric_sanity_check,
    parse_integer_set,
    parse_integer_value,
    small_case_enumeration_metadata,
    small_case_enumeration_check,
    strict_equivalence_check,
)
from scripts.utils import call_chat_completion, normalize_answer, short_text


VALID_NOTE_TYPES = {
    "FACT",
    "FAIL",
    "NUMERIC_CHECK",
    "SYMBOLIC_CHECK",
    "BOUND",
    "ENUMERATION",
    "STRATEGY",
    "CANDIDATE_SUPPORT",
}

VALID_CHECK_METHODS = {
    "none",
    "llm_admission",
    "sympy_simplify",
    "numeric_eval",
    "strict_equivalence",
    "small_case_enumeration",
}


def canonical_claim(claim: Any) -> str:
    text = str(claim or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def make_note_id(note_type: str, claim: str, source: str, round_id: int) -> str:
    payload = f"{note_type}|{canonical_claim(claim)}|{source}|{round_id}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def usage_total_tokens(usage: Any) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get("total_tokens")
    if isinstance(value, int):
        return value
    total = 0
    for key in ["prompt_tokens", "completion_tokens", "reasoning_tokens"]:
        if isinstance(usage.get(key), int):
            total += usage[key]
    return total


def _extract_json_object(text: str | None) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    starts = [match.start() for match in re.finditer(r"\{", raw)]
    for start in reversed(starts):
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(raw[start:index + 1])
                        return parsed if isinstance(parsed, dict) else None
                    except Exception:
                        break
    return None


def normalize_worker_claim(
    raw_claim: Any,
    *,
    round_id: int,
    source: str,
) -> dict[str, Any]:
    raw = raw_claim if isinstance(raw_claim, dict) else {}
    note_type = str(raw.get("type") or "STRATEGY").strip().upper()
    check_method = str(raw.get("check_method") or "none").strip().lower()
    claim = short_text(raw.get("claim") or "", 120)
    evidence = short_text(raw.get("evidence") or "", 180)
    raw_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}

    return {
        "note_id": make_note_id(note_type, claim, source, round_id),
        "round": round_id,
        "source": source,
        "type": note_type,
        "claim": claim,
        "evidence": evidence,
        "check_method": check_method,
        "status": "uncertain",
        "confidence": 0,
        "supports_answer": normalize_answer(raw.get("supports_answer")),
        "blocks_answer": normalize_answer(raw.get("blocks_answer")),
        "metadata": {
            **raw_metadata,
            **({"set_support_subtype": raw.get("subtype")} if raw.get("subtype") else {}),
        },
    }


def extract_intermediate_claims(worker_record: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = worker_record.get("parsed") or {}
    claims = parsed.get("intermediate_claims")
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims[:2] if isinstance(claim, dict)]


def _duplicate_verified_note(note: dict[str, Any], shared_context: dict[str, Any]) -> dict[str, Any] | None:
    claim_key = canonical_claim(note.get("claim"))
    for existing in shared_context.get("verified_notes", []) or []:
        if canonical_claim(existing.get("claim")) == claim_key:
            return existing
    return None


def _conflicts_with_rejected_answer(note: dict[str, Any], shared_context: dict[str, Any]) -> bool:
    supports_answer = normalize_answer(note.get("supports_answer"))
    if supports_answer is None:
        return False

    for item in shared_context.get("rejected_answers", []) or []:
        rejected = normalize_answer(item.get("answer") if isinstance(item, dict) else item)
        if rejected is None:
            continue
        strict_result = strict_equivalence_check(supports_answer, rejected)
        if strict_result is True:
            return True
        if strict_result is None and supports_answer == rejected:
            return True
    return False


def _tool_check_note(case: dict[str, Any], note: dict[str, Any]) -> tuple[str, str, int]:
    method = note.get("check_method")
    claim = note.get("claim") or ""

    if method == "sympy_simplify":
        result = check_equation_claim(claim)
    elif method == "numeric_eval":
        result = numeric_sanity_check(claim)
    elif method == "strict_equivalence":
        result = check_strict_equiv_function_claim(claim)
        if result is None:
            result = check_equation_claim(claim)
    elif method == "small_case_enumeration":
        result = small_case_enumeration_check(case, claim)
    elif method == "none":
        return "uncertain", "no check method was provided", 25
    else:
        return "uncertain", "tool check not applicable", 25

    if result is True:
        return "verified", f"{method} verified the equation claim", 90
    if result is False:
        return "rejected", f"{method} found the equation claim false", 90
    return "uncertain", f"{method} could not parse or verify the claim", 35


def enrich_set_note_metadata(case: dict[str, Any], note: dict[str, Any]) -> None:
    if str((case or {}).get("answer_type") or "").lower() != "set":
        return

    metadata = note.setdefault("metadata", {})
    subtype = str(metadata.get("set_support_subtype") or "").strip()

    if note.get("check_method") == "small_case_enumeration":
        enum_metadata = small_case_enumeration_metadata(case, note.get("claim") or "")
        if enum_metadata:
            metadata.update(enum_metadata)
            return

    supports_answer = note.get("supports_answer")
    blocks_answer = note.get("blocks_answer")
    support_set = parse_integer_set(supports_answer or "")
    block_set = parse_integer_set(blocks_answer or "")
    support_value = parse_integer_value(supports_answer)
    block_value = parse_integer_value(blocks_answer)

    membership_values = set()
    if support_value is not None:
        membership_values.add(support_value)
    membership_values.update(extract_membership_values_from_claim(note.get("claim") or ""))

    if not subtype:
        if metadata.get("complete") is True and support_set is not None:
            subtype = "completeness_evidence"
        elif block_value is not None or block_set is not None:
            subtype = "exclusion_evidence"
        elif membership_values:
            subtype = "membership_evidence"
        elif support_set is not None:
            subtype = "partial_enumeration"
        else:
            subtype = "membership_evidence"

    metadata["set_support_subtype"] = subtype

    if membership_values:
        metadata["membership_values"] = sorted(membership_values)
    elif support_set is not None and subtype != "completeness_evidence":
        metadata["membership_values"] = sorted(support_set)

    if block_value is not None:
        metadata["excluded_values"] = [block_value]
    elif block_set is not None:
        metadata["excluded_values"] = sorted(block_set)

    if support_set is not None:
        metadata.setdefault("value_set", sorted(support_set))
        metadata.setdefault("complete", False)


def should_call_llm_admission_fallback(
    note: dict[str, Any],
    result: dict[str, Any],
    settings: dict[str, Any],
) -> bool:
    if settings.get("use_llm_admission_fallback") is not True:
        return False
    if settings.get("client") is None:
        return False
    if result.get("status") != "uncertain":
        return False
    if note.get("type") == "STRATEGY":
        return False
    if not str(note.get("claim") or "").strip():
        return False
    return note.get("type") in {
        "FACT",
        "NUMERIC_CHECK",
        "SYMBOLIC_CHECK",
        "BOUND",
        "ENUMERATION",
        "CANDIDATE_SUPPORT",
    }


def build_llm_admission_prompt(
    case: dict[str, Any],
    note: dict[str, Any],
    shared_context: dict[str, Any],
) -> str:
    problem = case.get("problem", "")
    answer_type = case.get("answer_type")
    rejected_answers = [
        item.get("answer") if isinstance(item, dict) else item
        for item in shared_context.get("rejected_answers", []) or []
    ]
    verified_notes = [
        {
            "note_id": item.get("note_id"),
            "type": item.get("type"),
            "claim": item.get("claim"),
            "evidence": item.get("evidence"),
        }
        for item in (shared_context.get("verified_notes", []) or [])[-12:]
    ]

    return f"""
You are an admission judge for a math shared-context system.

The gold answer is NOT provided. Do not guess or reveal the final answer.
Judge only whether the proposed note's claim is supported by its evidence and the problem statement.
Do not generate a new answer.
Be conservative: if the claim is not clearly supported, return uncertain.

Return ONLY JSON:
{{
  "status": "verified | rejected | uncertain",
  "reason": "one concise sentence",
  "confidence": 0-100
}}

Answer type:
{answer_type}

Previously rejected final answers:
{json.dumps(rejected_answers, ensure_ascii=False)}

Existing verified notes:
{json.dumps(verified_notes, ensure_ascii=False, indent=2)}

Proposed note:
{json.dumps(note, ensure_ascii=False, indent=2)}

Problem:
{problem}
"""


def run_llm_admission(
    case: dict[str, Any],
    note: dict[str, Any],
    shared_context: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    client = settings.get("client")
    if client is None:
        return {
            "status": "uncertain",
            "reason": "LLM admission was requested but no client was provided.",
            "confidence": 0,
            "api_call": False,
            "usage": {},
            "raw_output": "",
            "finish_reason": "no_client",
        }

    started = time.perf_counter()
    result = call_chat_completion(
        client,
        build_llm_admission_prompt(case, note, shared_context),
        temperature=float(settings.get("admission_temperature", 0.0)),
        max_tokens=int(settings.get("admission_max_tokens", 512)),
    )
    result["wall_time_seconds"] = time.perf_counter() - started
    parsed = _extract_json_object(result.get("content"))
    if not isinstance(parsed, dict):
        parsed = {}

    status = str(parsed.get("status") or "uncertain").strip().lower()
    if status not in {"verified", "rejected", "uncertain"}:
        status = "uncertain"

    try:
        confidence = int(float(parsed.get("confidence", 0)))
    except Exception:
        confidence = 0
    confidence = max(0, min(100, confidence))

    return {
        "status": status,
        "reason": short_text(parsed.get("reason") or "No reliable admission reason was extracted.", 300),
        "confidence": confidence,
        "api_call": True,
        "usage": result.get("usage") or {},
        "raw_output": result.get("content", ""),
        "finish_reason": result.get("finish_reason"),
        "error": result.get("error"),
        "wall_time_seconds": result.get("wall_time_seconds"),
    }


def admit_one_note(
    case: dict[str, Any],
    note: dict[str, Any],
    shared_context: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "note": note,
        "status": "uncertain",
        "reason": "",
        "duplicate_verified_note": False,
        "existing_note_id": None,
        "api_call": False,
        "usage": {},
    }

    if not note.get("claim"):
        result.update(status="rejected", reason="empty claim")
    elif len(str(note.get("claim"))) > 200:
        result.update(status="rejected", reason="claim is too long")
    elif note.get("type") not in VALID_NOTE_TYPES:
        result.update(status="rejected", reason=f"invalid note type: {note.get('type')}")
    elif note.get("check_method") not in VALID_CHECK_METHODS:
        result.update(status="rejected", reason=f"invalid check method: {note.get('check_method')}")
    else:
        duplicate = _duplicate_verified_note(note, shared_context)
        if duplicate is not None:
            note["status"] = "verified"
            note["confidence"] = duplicate.get("confidence", 0)
            result.update(
                status="verified",
                reason="duplicate of existing verified note",
                duplicate_verified_note=True,
                existing_note_id=duplicate.get("note_id"),
            )
            return result

        if _conflicts_with_rejected_answer(note, shared_context):
            result.update(status="rejected", reason="claim supports an already rejected answer")
        elif note.get("check_method") == "llm_admission":
            admission = run_llm_admission(case, note, shared_context, settings)
            result.update(admission)
        else:
            status, reason, confidence = _tool_check_note(case, note)
            result.update(status=status, reason=reason, confidence=confidence)
            if should_call_llm_admission_fallback(note, result, settings):
                tool_result = {
                    "tool_status": result.get("status"),
                    "tool_reason": result.get("reason"),
                    "tool_confidence": result.get("confidence"),
                }
                admission = run_llm_admission(case, note, shared_context, settings)
                result.update(admission)
                result.update(tool_result)

    enrich_set_note_metadata(case, note)
    note["status"] = result.get("status")
    note["confidence"] = int(result.get("confidence") or 0)
    note["metadata"] = {
        **(note.get("metadata") or {}),
        "admission_reason": result.get("reason"),
    }
    result["note"] = note
    return result


def admit_worker_claims(
    case: dict[str, Any],
    worker_record: dict[str, Any],
    shared_context: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    source = f"worker_{worker_record.get('worker_id')}"
    round_id = int(worker_record.get("round") or 0)
    raw_claims = extract_intermediate_claims(worker_record)
    normalized_notes = [
        normalize_worker_claim(raw_claim, round_id=round_id, source=source)
        for raw_claim in raw_claims
    ]

    verified_notes = []
    rejected_notes = []
    admission_results = []

    for note in normalized_notes:
        admission = admit_one_note(case, note, shared_context, settings)
        admission_results.append(admission)
        admitted_note = admission.get("note") or note
        if admission.get("duplicate_verified_note") is True:
            continue
        if admission.get("status") == "verified":
            verified_notes.append(admitted_note)
        elif admission.get("status") in {"rejected", "uncertain"}:
            rejected_notes.append(admitted_note)

    return {
        "verified_notes": verified_notes,
        "rejected_notes": rejected_notes,
        "admission_results": admission_results,
        "admission_evaluations": len(admission_results),
        "admission_calls": sum(1 for item in admission_results if item.get("api_call") is True),
        "admission_tokens": sum(usage_total_tokens(item.get("usage")) for item in admission_results),
    }


def note_brief(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "note_id": note.get("note_id"),
        "round": note.get("round"),
        "source": note.get("source"),
        "type": note.get("type"),
        "claim": note.get("claim"),
        "evidence": note.get("evidence"),
        "status": note.get("status"),
        "confidence": note.get("confidence"),
        "supports_answer": note.get("supports_answer"),
        "blocks_answer": note.get("blocks_answer"),
    }


def format_verified_notes(notes: list[dict[str, Any]], limit: int = 12) -> str:
    if not notes:
        return "No verified shared notes yet."
    lines = []
    for note in notes[-limit:]:
        lines.append(
            "- "
            f"note_id={note.get('note_id')} | "
            f"type={note.get('type')} | "
            f"claim={note.get('claim')} | "
            f"evidence={note.get('evidence')} | "
            f"source={note.get('source')} | "
            f"round={note.get('round')}"
        )
    return "\n".join(lines)
