# scripts/utils/math_utils.py

try:
    from math_verify import parse, verify
except ModuleNotFoundError:
    parse = None
    verify = None


def _require_math_verify() -> None:
    if parse is None or verify is None:
        raise RuntimeError(
            "math_verify is required for safe_verify/equivalent. "
            "Install project dependencies with `pip install -r requirements.txt`."
        )


def normalize_answer(ans: str | None) -> str | None:
    if ans is None:
        return None

    ans = str(ans).strip()
    if not ans:
        return None

    return ans


def _candidate_forms(answer: str | None) -> list[str]:
    answer = normalize_answer(answer)
    if answer is None:
        return []

    candidates = [answer]
    boxed = extract_boxed(answer)
    if boxed is not None:
        candidates.append(boxed)

    candidates.extend([
        f"\\boxed{{{answer}}}",
        f"Final Answer: \\boxed{{{answer}}}",
    ])

    out = []
    seen = set()
    for candidate in candidates:
        candidate = normalize_answer(candidate)
        if candidate is not None and candidate not in seen:
            out.append(candidate)
            seen.add(candidate)
    return out


def extract_boxed(text: str | None) -> str | None:
    if not text:
        return None

    text = str(text)
    key = "\\boxed{"
    start = text.rfind(key)

    if start == -1:
        return None

    i = start + len(key)
    depth = 1
    ans_chars = []

    while i < len(text):
        ch = text[i]

        if ch == "{":
            depth += 1
            ans_chars.append(ch)
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return normalize_answer("".join(ans_chars))
            ans_chars.append(ch)
        else:
            ans_chars.append(ch)

        i += 1

    return None


def safe_verify(gold: str | None, pred_answer: str | None) -> bool:
    if gold is None or pred_answer is None:
        return False

    _require_math_verify()

    for gold_candidate in _candidate_forms(gold):
        for pred_candidate in _candidate_forms(pred_answer):
            try:
                if verify(parse(gold_candidate), parse(pred_candidate)):
                    return True
            except Exception:
                pass

    return False


def equivalent(ans1: str | None, ans2: str | None) -> bool:
    if ans1 is None or ans2 is None:
        return False

    _require_math_verify()

    for candidate1 in _candidate_forms(ans1):
        for candidate2 in _candidate_forms(ans2):
            try:
                if verify(parse(candidate1), parse(candidate2)):
                    return True
            except Exception:
                pass

    return False
