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
    timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing in .env")

    return OpenAI(
        api_key=api_key,
        base_url=base_url if base_url else None,
        timeout=timeout,
    )


def response_usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None

    if hasattr(usage, "model_dump"):
        return usage.model_dump()

    if isinstance(usage, dict):
        return usage

    return {"raw": str(usage)}


def _object_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return None


def responses_usage_to_legacy_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None

    raw = _object_to_dict(usage)
    if raw is None:
        return {"raw": str(usage)}

    return {
        "prompt_tokens": raw.get("input_tokens"),
        "completion_tokens": raw.get("output_tokens"),
        "total_tokens": raw.get("total_tokens"),
        "completion_tokens_details": raw.get("output_tokens_details"),
        "prompt_tokens_details": raw.get("input_tokens_details"),
        "raw": raw,
    }


def _use_openai_responses_api() -> bool:
    _load_env()
    return os.getenv("OPENAI_USE_RESPONSES_API", "0") == "1"


def _request_timeout_seconds() -> float:
    _load_env()
    return float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))


def _openai_reasoning_effort() -> str:
    _load_env()
    effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower()
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    if effort not in allowed:
        raise ValueError(
            "OPENAI_REASONING_EFFORT must be one of: "
            f"{', '.join(sorted(allowed))}."
        )
    return effort


def _responses_output_text(response: Any) -> str:
    response_dict = _object_to_dict(response) or {}
    output_text = getattr(response, "output_text", None) or response_dict.get("output_text")
    if output_text:
        return str(output_text)

    chunks = []
    output = getattr(response, "output", None) or response_dict.get("output")
    if not isinstance(output, list):
        return ""

    for item in output:
        item_type = getattr(item, "type", None)
        item_dict = _object_to_dict(item) or {}
        item_type = item_type or item_dict.get("type")
        if item_type != "message":
            continue

        content = getattr(item, "content", None)
        if content is None:
            content = item_dict.get("content")
        if not isinstance(content, list):
            continue

        for part in content:
            part_dict = _object_to_dict(part) or {}
            part_type = getattr(part, "type", None) or part_dict.get("type")
            if part_type not in {"output_text", "text"}:
                continue
            text = getattr(part, "text", None)
            if text is None:
                text = part_dict.get("text")
            if text:
                chunks.append(str(text))

    return "".join(chunks)


def _responses_finish_metadata(response: Any) -> dict[str, Any]:
    response_dict = _object_to_dict(response) or {}
    status = getattr(response, "status", None) or response_dict.get("status")
    incomplete_details = (
        getattr(response, "incomplete_details", None)
        or response_dict.get("incomplete_details")
    )
    incomplete_dict = _object_to_dict(incomplete_details) or {}
    incomplete_reason = (
        getattr(incomplete_details, "reason", None)
        if incomplete_details is not None
        else None
    ) or incomplete_dict.get("reason")

    if status == "completed":
        finish_reason = "stop"
    elif status == "incomplete":
        finish_reason = "length" if incomplete_reason == "max_output_tokens" else incomplete_reason
    else:
        finish_reason = status

    return {
        "finish_reason": finish_reason,
        "response_status": status,
        "incomplete_reason": incomplete_reason,
    }


def _deepseek_thinking_mode() -> str:
    _load_env()
    return os.getenv("DEEPSEEK_THINKING", "").strip().lower()


def _deepseek_completion_kwargs(thinking: str) -> dict[str, Any]:
    if not thinking:
        return {}

    if thinking not in {"enabled", "disabled"}:
        raise RuntimeError(
            "DEEPSEEK_THINKING must be empty, 'enabled', or 'disabled'."
        )

    kwargs: dict[str, Any] = {
        "extra_body": {
            "thinking": {
                "type": thinking,
            },
        },
    }

    if thinking == "enabled":
        reasoning_effort = os.getenv("REASONING_EFFORT", "high").strip().lower()
        if reasoning_effort not in {"high", "max"}:
            raise RuntimeError("REASONING_EFFORT must be 'high' or 'max'.")
        kwargs["reasoning_effort"] = reasoning_effort

    return kwargs


def _call_openai_responses_api(
    client: OpenAI,
    prompt: str,
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    reasoning_effort = _openai_reasoning_effort()
    print("[LLM CONFIG]", {
        "provider_api": "openai_responses",
        "model": model,
        "use_responses_api": True,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": max_tokens,
        "temperature": temperature,
        "request_timeout_seconds": _request_timeout_seconds(),
    })

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_tokens,
            reasoning={"effort": reasoning_effort},
            temperature=temperature,
        )
    except Exception as e:
        error = repr(e)
        print(
            "[OPENAI RESPONSES API ERROR] "
            f"model={model}, "
            f"reasoning_effort={reasoning_effort}, "
            f"max_output_tokens={max_tokens}, "
            f"error={error}"
        )
        return {
            "content": "",
            "finish_reason": "api_error",
            "usage": None,
            "error": error,
            "response_status": "api_error",
            "incomplete_reason": None,
        }

    finish_metadata = _responses_finish_metadata(response)
    return {
        "content": _responses_output_text(response),
        "finish_reason": finish_metadata["finish_reason"],
        "usage": responses_usage_to_legacy_dict(getattr(response, "usage", None)),
        "error": None,
        "response_status": finish_metadata["response_status"],
        "incomplete_reason": finish_metadata["incomplete_reason"],
    }


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
            if _use_openai_responses_api():
                result = _call_openai_responses_api(
                    client,
                    prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if result.get("error") is None:
                    return result
                last_error = result.get("error")
                if attempt < retries:
                    time.sleep(sleep_seconds)
                    continue
                return result

            thinking_mode = _deepseek_thinking_mode()
            request_kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                **_deepseek_completion_kwargs(thinking_mode),
            }
            print("[LLM CONFIG]", {
                "provider_api": "chat_completions",
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "use_responses_api": False,
                "reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower(),
                "request_timeout_seconds": _request_timeout_seconds(),
                "deepseek_thinking": thinking_mode,
            })

            resp = client.chat.completions.create(
                **request_kwargs,
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
        "error": None,
    }

    for attempt in range(retry):
        try:
            if _use_openai_responses_api():
                result = _call_openai_responses_api(
                    client,
                    prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if result.get("error") is not None:
                    print(
                        f"[WARN] API error, retry {attempt + 1}/{retry}: "
                        f"{result.get('error')}"
                    )
                    last_result = result
                    time.sleep(sleep_seconds)
                    continue

                if (result.get("content") or "").strip():
                    return result

                print(
                    f"[WARN] empty output, retry {attempt + 1}/{retry}, "
                    f"finish_reason={result.get('finish_reason')}"
                )

                last_result = result

                if result.get("finish_reason") == "length":
                    return result

                time.sleep(sleep_seconds)
                continue

            thinking_mode = _deepseek_thinking_mode()
            request_kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                **_deepseek_completion_kwargs(thinking_mode),
            }

            resp = client.chat.completions.create(
                **request_kwargs,
            )

            choice = resp.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason
            usage = response_usage_to_dict(getattr(resp, "usage", None))

            result = {
                "content": content,
                "finish_reason": finish_reason,
                "usage": usage,
                "error": None,
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
