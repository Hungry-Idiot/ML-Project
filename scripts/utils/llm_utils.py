# scripts/utils/llm_utils.py

import os
import time
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        return False

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None


def _load_env() -> None:
    load_dotenv()


def _require_openai() -> None:
    if OpenAI is None:
        raise RuntimeError(
            "openai is required for LLM calls. "
            "Install project dependencies with `pip install -r requirements.txt`."
        )


def get_model_name() -> str:
    _load_env()

    model = os.getenv("MODEL_NAME")
    if not model:
        raise RuntimeError("MODEL_NAME is missing in .env")
    return model


def get_client() -> OpenAI:
    _load_env()
    _require_openai()

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing in .env")

    return OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )


def response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return {"raw": str(usage)}


def call_chat_completion(
    client: OpenAI,
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    retries: int = 0,
    sleep_seconds: float = 1.0,
) -> dict[str, Any]:
    model = model or get_model_name()
    last_error = None

    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            choice = resp.choices[0]
            return {
                "content": choice.message.content or "",
                "finish_reason": choice.finish_reason,
                "usage": response_usage_to_dict(getattr(resp, "usage", None)),
                "error": None,
            }

        except Exception as e:
            last_error = repr(e)
            if attempt < retries:
                time.sleep(sleep_seconds)

    return {
        "content": "",
        "finish_reason": "api_error",
        "usage": None,
        "error": last_error,
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
