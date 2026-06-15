# scripts/utils/report_utils.py

from typing import Any


def pct(x: int | float, total: int | float) -> str:
    if total == 0:
        return "N/A"
    return f"{x / total:.2%}"


def short_text(x: Any, max_len: int = 160) -> str:
    if x is None:
        return ""

    s = str(x).replace("\n", " ").strip()
    if len(s) <= max_len:
        return s

    return s[:max_len] + "..."


def tail_text(x: Any, max_len: int = 800) -> str:
    if x is None:
        return ""

    s = str(x).strip()
    if len(s) <= max_len:
        return s

    return s[-max_len:]


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        clean_row = []
        for item in row:
            s = str(item)
            s = s.replace("\n", "<br>")
            s = s.replace("|", "\\|")
            clean_row.append(s)
        lines.append("| " + " | ".join(clean_row) + " |")

    return "\n".join(lines)