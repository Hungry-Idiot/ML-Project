import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from math_verify import parse, verify


load_dotenv()


def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing in .env")

    return OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )


def get_model_name() -> str:
    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")
    return model


def extract_boxed(text: str | None) -> str | None:
    """
    Extract the content of the last \\boxed{...}.
    Supports nested braces, e.g. \\boxed{\\frac{1}{2}}.
    """
    if not text:
        return None

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
                return "".join(ans_chars).strip()
            ans_chars.append(ch)
        else:
            ans_chars.append(ch)

        i += 1

    return None


def _candidate_forms(answer: str) -> list[str]:
    return [
        answer,
        f"\\boxed{{{answer}}}",
        f"Final Answer: \\boxed{{{answer}}}",
    ]


def equivalent(ans1: str | None, ans2: str | None) -> bool:
    """
    Check mathematical equivalence between two extracted answers.
    """
    if ans1 is None or ans2 is None:
        return False

    for a in _candidate_forms(ans1):
        for b in _candidate_forms(ans2):
            try:
                if verify(parse(a), parse(b)):
                    return True
            except Exception:
                pass

    return False


def safe_verify(gold: str, pred_answer: str | None) -> bool:
    """
    Check whether pred_answer is mathematically equivalent to gold.
    """
    return equivalent(gold, pred_answer)


def response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    """
    Convert OpenAI-compatible usage object to a normal dict when possible.
    """
    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return {
        "raw": str(usage)
    }


def call_llm_final_only(
    client: OpenAI,
    problem: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 32768,
    retry: int = 1,
    sleep_seconds: float = 1.0,
) -> dict[str, Any]:
    """
    Call an OpenAI-compatible chat completion API.

    Return a dict:
    {
        "content": str,
        "finish_reason": str | None,
        "usage": dict | None,
    }

    For hard benchmarks, retry defaults to 1.
    If finish_reason == "length", retrying usually wastes time and tokens,
    so this function returns immediately.
    """
    model = get_model_name()

    prompt = f"""
You are solving a very hard olympiad-style math problem.

Please solve the problem carefully. You may show your reasoning.

At the end of your response, output the final answer in exactly this format:

Final Answer: \\boxed{{your_answer}}

Problem:
{problem}
"""

    last_result = {
        "content": "",
        "finish_reason": None,
        "usage": None,
    }

    for attempt in range(retry):
        try:
            reasoning_effort = os.getenv("REASONING_EFFORT", "low")

            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body={
                    "reasoning_effort": reasoning_effort,
                },
            )

            choice = resp.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            usage = response_usage_to_dict(getattr(resp, "usage", None))

            result = {
                "content": content,
                "finish_reason": finish_reason,
                "usage": usage,
            }

            if content.strip():
                return result

            print(
                f"[WARN] empty output, retry {attempt + 1}/{retry}, "
                f"finish_reason={finish_reason}"
            )

            last_result = result

            if finish_reason == "length":
                return result

        except Exception as e:
            print(f"[WARN] API error, retry {attempt + 1}/{retry}: {repr(e)}")
            last_result = {
                "content": "",
                "finish_reason": "api_error",
                "usage": None,
                "error": repr(e),
            }

        time.sleep(sleep_seconds)

    return last_result