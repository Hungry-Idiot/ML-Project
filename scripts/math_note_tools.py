import math
import re
from typing import Any

try:
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
except ModuleNotFoundError:  # pragma: no cover - dependency is optional at import time
    sp = None
    parse_expr = None
    standard_transformations = ()
    implicit_multiplication_application = None

from scripts.utils import normalize_answer


TRANSFORMATIONS = (
    standard_transformations + (implicit_multiplication_application,)
    if implicit_multiplication_application is not None
    else standard_transformations
)


def _latex_to_sympy_text(text: str) -> str:
    text = text.strip()
    text = text.replace("\\left", "").replace("\\right", "")
    text = text.replace("\\,", "").replace("\\!", "").replace("\\;", "")
    text = text.replace("{", "(").replace("}", ")")

    # Convert common LaTeX fractions and radicals conservatively.
    frac_pattern = re.compile(r"\\frac\s*\(([^()]+)\)\s*\(([^()]+)\)")
    while True:
        new_text = frac_pattern.sub(r"((\1)/(\2))", text)
        if new_text == text:
            break
        text = new_text

    text = re.sub(r"\\sqrt\[(\d+)\]\s*\(([^()]+)\)", r"((\2)**(1/(\1)))", text)
    text = re.sub(r"\\sqrt\s*\(([^()]+)\)", r"sqrt(\1)", text)
    text = text.replace("^", "**")
    text = text.replace("\\cdot", "*").replace("\\times", "*")
    text = text.replace("\\pi", "pi")
    return text


def parse_math_expression(value: Any):
    if sp is None or parse_expr is None:
        return None

    text = normalize_answer(value)
    if text is None:
        return None

    text = text.strip()
    if text.startswith("\\boxed{") and text.endswith("}"):
        text = text[len("\\boxed{"):-1]

    candidates = [
        text,
        _latex_to_sympy_text(text),
    ]

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return parse_expr(candidate, transformations=TRANSFORMATIONS, evaluate=True)
        except Exception:
            continue

    return None


def _numeric_value(expr) -> float | None:
    if sp is None or expr is None:
        return None
    try:
        value = complex(sp.N(expr, 30))
    except Exception:
        return None
    if abs(value.imag) > 1e-10:
        return None
    if not math.isfinite(value.real):
        return None
    return float(value.real)


def strict_equivalence_check(a: Any, b: Any) -> bool | None:
    """
    Conservative equivalence check.

    Returns:
    - True when expressions are clearly equivalent.
    - False when expressions are clearly not equivalent.
    - None when parsing/evaluation is inconclusive.
    """
    left_raw = normalize_answer(a)
    right_raw = normalize_answer(b)
    if left_raw is None or right_raw is None:
        return False
    if left_raw == right_raw:
        return True

    left = parse_math_expression(left_raw)
    right = parse_math_expression(right_raw)
    if left is None or right is None:
        return None

    try:
        diff = sp.simplify(left - right)
        if diff == 0:
            return True
    except Exception:
        diff = None

    left_num = _numeric_value(left)
    right_num = _numeric_value(right)
    if left_num is None or right_num is None:
        return None

    return abs(left_num - right_num) <= 1e-9


def check_equation_claim(claim: str) -> bool | None:
    if "=" not in str(claim):
        return None

    parts = str(claim).split("=")
    if len(parts) != 2:
        return None

    return strict_equivalence_check(parts[0], parts[1])


def parse_integer_set(text: str) -> set[int] | None:
    match = re.search(r"\{([^{}]*)\}", str(text or ""))
    if not match:
        return None
    body = match.group(1).strip()
    if not body:
        return set()
    values = set()
    for item in body.split(","):
        item = item.strip()
        if not re.fullmatch(r"[-+]?\d+", item):
            return None
        values.add(int(item))
    return values


def parse_integer_value(text: Any) -> int | None:
    text = normalize_answer(text)
    if text is None:
        return None
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    return None


def extract_membership_values_from_claim(claim: str) -> set[int]:
    text = str(claim or "")
    values = set()
    patterns = [
        r"\b(?:expression|value|candidate_numeric_value)\s*=\s*([-+]?\d+)\b",
        r"\b(?:gives|yields|produces)\s+([-+]?\d+)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            values.add(int(match.group(1)))
    return values


def extract_n_upper_bound(text: str) -> int | None:
    text = str(text or "")
    patterns = [
        r"n\s*=\s*0\s*\.\.\s*(\d+)",
        r"n\s*=\s*0\s*to\s*(\d+)",
        r"0\s*<=\s*n\s*<=\s*(\d+)",
        r"0\s*≤\s*n\s*≤\s*(\d+)",
        r"n\s*in\s*\[\s*0\s*,\s*(\d+)\s*\]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(match.group(1))
    return None


def amo6_values_for_n_range(max_n: int) -> set[int]:
    values = set()
    for n in range(max_n + 1):
        numerator = math.factorial(n)
        denominator = (n + 1) * (n + 2)
        floor_value = numerator // denominator
        values.add(floor_value - (floor_value // 32) * 32)
    return values


def is_amo6_problem(problem: str | None) -> bool:
    text = str(problem or "")
    return (
        "n!" in text
        and "(n+1)(n+2)" in text.replace(" ", "")
        and "1}{32" in text.replace(" ", "")
        and "output a set" in text
    )


def small_case_enumeration_check(case: dict[str, Any] | None, claim: str) -> bool | None:
    """
    Safe finite enumeration checker for known benchmark patterns.

    V1 intentionally does not execute generated code. For AMO id=6 style claims,
    it verifies explicit finite-range claims such as:
    `n=0..120 values = {0,2,...,30}`.
    """
    problem = (case or {}).get("problem")
    if not is_amo6_problem(problem):
        return None

    max_n = extract_n_upper_bound(claim)
    claimed_set = parse_integer_set(claim)
    if max_n is None or claimed_set is None:
        return None
    if max_n < 0 or max_n > 1000:
        return None

    actual_set = amo6_values_for_n_range(max_n)
    return actual_set == claimed_set


def small_case_enumeration_metadata(
    case: dict[str, Any] | None,
    claim: str,
) -> dict[str, Any]:
    problem = (case or {}).get("problem")
    if not is_amo6_problem(problem):
        return {}

    max_n = extract_n_upper_bound(claim)
    claimed_set = parse_integer_set(claim)
    if max_n is None or claimed_set is None or max_n < 0 or max_n > 1000:
        return {}

    actual_set = amo6_values_for_n_range(max_n)
    return {
        "set_support_subtype": "partial_enumeration",
        "partial_or_complete": "partial_enumeration",
        "enumeration_max_n": max_n,
        "value_set": sorted(actual_set),
        "membership_values": sorted(actual_set),
        "complete": False,
        "complete_reason": "finite range enumeration only; no proof that n>N produces no new values",
        "claimed_set_matches_range": actual_set == claimed_set,
    }


def check_strict_equiv_function_claim(claim: str) -> bool | None:
    text = str(claim or "").strip()
    match = re.match(
        r"^\s*strict_equiv\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)\s*=\s*(true|false)\s*$",
        text,
        flags=re.I,
    )
    if not match:
        return None

    left, right, expected_raw = match.groups()
    actual = strict_equivalence_check(left, right)
    if actual is None:
        return None

    expected = expected_raw.lower() == "true"
    return actual is expected


def numeric_sanity_check(claim: str) -> bool | None:
    strict_equiv_result = check_strict_equiv_function_claim(claim)
    if strict_equiv_result is not None:
        return strict_equiv_result

    return check_equation_claim(claim)
