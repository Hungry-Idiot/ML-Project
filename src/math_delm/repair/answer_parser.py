from __future__ import annotations

import json
import re
from typing import Any

from src.math_delm.utils import extract_boxed, normalize_answer


def strip_think_blocks(text: str | None) -> str:
    if text is None:
        return ""

    cleaned = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.S | re.I)
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("```", "")
    return cleaned.strip()


def _json_object_or_none(candidate: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    if isinstance(parsed, dict):
        return parsed

    return None


def _extract_last_balanced_json_object(text: str) -> dict[str, Any] | None:
    starts = [match.start() for match in re.finditer(r"\{", text)]

    for start in reversed(starts):
        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

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
                    parsed = _json_object_or_none(text[start:index + 1])
                    if parsed is not None:
                        return parsed
                    break

    return None


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """
    utils 里没有 JSON 抽取函数，所以这里单独定义。
    用于从模型输出中尽量解析 JSON。
    """
    original = text or ""
    cleaned = strip_think_blocks(original)

    parsed = _json_object_or_none(cleaned.strip())
    if parsed is not None:
        return parsed

    parsed = _extract_last_balanced_json_object(cleaned)
    if parsed is not None:
        return parsed

    return _extract_last_balanced_json_object(original)


def _normalized_non_empty_answer(value: Any) -> str | None:
    answer = normalize_answer(value)

    if answer is None:
        return None

    invalid_values = {
        "",
        "none",
        "null",
        "n/a",
        "na",
        "no answer",
        "no_answer",
        "cannot determine",
        "unknown",
    }

    if answer.lower().strip() in invalid_values:
        return None

    return answer


def _answer_from_parsed(parsed: dict[str, Any] | None) -> str | None:
    if not parsed:
        return None

    for key in [
        "final_answer",
        "candidate_answer",
        "selected_answer",
        "submitted_answer",
        "answer",
    ]:
        value = _normalized_non_empty_answer(parsed.get(key))
        if value is not None:
            return value

    return None


def parse_answer_from_output(text: str | None, parsed: dict[str, Any] | None = None) -> str | None:
    value = _answer_from_parsed(parsed)
    if value is not None:
        return value

    if parsed is None:
        parsed = extract_json_object(text)
        value = _answer_from_parsed(parsed)
        if value is not None:
            return value

    cleaned = strip_think_blocks(text)

    answer_patterns = [
        r"^\s*FINAL_ANSWER\s*:\s*(.+?)\s*$",
        r"^\s*Final\s+Answer\s*:\s*(.+?)\s*$",
        r"^\s*final\s+answer\s+is\s+(.+?)\s*$",
        r"^\s*Answer\s*:\s*(.+?)\s*$",
    ]

    for pattern in answer_patterns:
        match = re.search(pattern, cleaned, flags=re.I | re.M)
        if match:
            value = _normalized_non_empty_answer(match.group(1))
            if value is not None:
                return value

    boxed = _normalized_non_empty_answer(extract_boxed(text or ""))
    if boxed is not None:
        return boxed

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if lines:
        last_line = lines[-1]
        looks_like_explanation = re.search(
            r"\b(therefore|because|hence|since|so|we|the answer|final answer|solution)\b",
            last_line,
            flags=re.I,
        )
        if len(last_line) <= 80 and looks_like_explanation is None:
            return _normalized_non_empty_answer(last_line)

    return None


def is_valid_answer(answer: str | None) -> bool:
    answer = normalize_answer(answer)

    if answer is None:
        return False

    invalid_values = {
        "none",
        "null",
        "n/a",
        "na",
        "no answer",
        "no_answer",
        "cannot determine",
        "empty",
        "unknown",
        "unparseable",
        "invalid",
    }

    return answer.lower().strip() not in invalid_values


def is_truncated_answer_item(item: dict[str, Any]) -> bool:
    return item.get("finish_reason") == "length"


def is_parser_invalid_item(item: dict[str, Any]) -> bool:
    parser_debug = item.get("parser_debug") or {}
    return bool(item.get("raw_output")) and parser_debug.get("extracted_answer") is None
