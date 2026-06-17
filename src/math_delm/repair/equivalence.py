from __future__ import annotations

from typing import Any

from src.math_delm.utils import equivalent, normalize_answer, safe_verify
from src.math_delm import config as cfg
from src.math_delm.repair.math_note_tools import strict_equivalence_check


def answer_equiv(a: str | None, b: str | None) -> bool:
    a = normalize_answer(a)
    b = normalize_answer(b)

    if a is None and b is None:
        return True

    if a is None or b is None:
        return False

    if a == b:
        return True

    return equivalent(a, b)


def verify_answer_with_details(gold: str | None, answer: str | None) -> tuple[bool, dict[str, Any]]:
    original_result = safe_verify(gold, answer)
    strict_result = strict_equivalence_check(gold, answer) if cfg.USE_STRICT_EQUIV else None

    if cfg.USE_STRICT_EQUIV and strict_result is not None:
        final_result = strict_result
    else:
        final_result = original_result

    return bool(final_result), {
        "strict_equiv_result": strict_result,
        "original_equiv_result": original_result,
        "final_equiv_result": bool(final_result),
        "use_strict_equiv": cfg.USE_STRICT_EQUIV,
    }


def safe_verify_feedback(gold: str | None, answer: str | None) -> bool:
    correct, _ = verify_answer_with_details(gold, answer)
    return correct


def answer_in_list(answer: str | None, answer_list: list[str | None]) -> bool:
    answer = normalize_answer(answer)

    if answer is None:
        return False

    for candidate in answer_list:
        candidate = normalize_answer(candidate)
        if candidate is None:
            continue

        if answer == candidate:
            return True

        if equivalent(answer, candidate):
            return True

    return False
