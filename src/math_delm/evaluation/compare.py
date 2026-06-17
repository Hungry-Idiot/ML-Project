from __future__ import annotations

from typing import Any


def _method_summary(summary: dict[str, Any], method_key: str) -> dict[str, Any]:
    if method_key in summary:
        return summary[method_key]
    return summary.get("summary", {}).get(method_key, {})


def compare_method_summaries(main_summary: dict[str, Any], delm_summary: dict[str, Any]) -> dict[str, Any]:
    main = _method_summary(main_summary, "main_agent")
    delm = _method_summary(delm_summary, "delm_lite")
    return {
        "main_agent": main,
        "delm_lite": delm,
        "delm_minus_main_solved": delm.get("solved", 0) - main.get("solved", 0),
        "delm_minus_main_api_calls": delm.get("api_calls", 0) - main.get("api_calls", 0),
        "delm_minus_main_tokens": delm.get("total_tokens", 0) - main.get("total_tokens", 0),
    }

