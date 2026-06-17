from src.math_delm.utils.llm import call_chat_completion, get_client, get_model_name
from src.math_delm.utils import append_jsonl
from src.math_delm import config as cfg
from typing import Any


def call_llm(
    client,
    prompt: str,
    *,
    temperature: float,
    max_tokens: int | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    resolved_max_tokens = cfg.MAX_TOKENS if max_tokens is None else max_tokens
    result = call_chat_completion(
        client,
        prompt,
        temperature=temperature,
        max_tokens=resolved_max_tokens,
        retries=retries,
    )

    if result.get("error"):
        append_jsonl(cfg.ERROR_PATH, {
            "error": result.get("error"),
            "finish_reason": result.get("finish_reason"),
            "prompt_tail": prompt[-1000:],
        })

    return result


__all__ = ["call_chat_completion", "get_client", "get_model_name", "call_llm"]
