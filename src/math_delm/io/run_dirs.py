from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src.math_delm.config import relevant_environment


def _safe_part(value: str | None) -> str:
    text = str(value or "unknown")
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "" for ch in text)[:80]


def build_run_id(dataset: str, model: str | None, agent: str, limit: int) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (
        f"{timestamp}__dataset-{_safe_part(dataset)}__model-{_safe_part(model)}"
        f"__agent-{_safe_part(agent)}__n-{limit if limit > 0 else 'all'}"
    )


def create_run_dirs(output_root: str | Path, run_id: str) -> dict[str, Path]:
    root = Path(output_root) / run_id
    dirs = {
        "root": root,
        "sc3": root / "sc3",
        "repair": root / "repair",
        "main_agent": root / "repair" / "main_agent",
        "delm_lite": root / "repair" / "delm_lite",
        "compare": root / "compare",
        "logs": root / "logs",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    return dirs


def git_commit_hash() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def write_run_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    data = {
        **manifest,
        "git_commit": manifest.get("git_commit") or git_commit_hash(),
        "relevant_environment": manifest.get("relevant_environment") or relevant_environment(),
        "cwd": os.getcwd(),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_run_config(run_dir: Path, config: dict[str, Any]) -> None:
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

