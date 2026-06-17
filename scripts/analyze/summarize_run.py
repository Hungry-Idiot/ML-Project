from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a structured outputs/runs/<run_id> directory.")
    parser.add_argument("run_dir", help="Path to outputs/runs/<run_id>")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    manifest = read_json(run_dir / "manifest.json")
    config = read_json(run_dir / "config.json")
    main_summary = read_json(run_dir / "repair" / "main_agent" / "summary.json")
    delm_summary = read_json(run_dir / "repair" / "delm_lite" / "summary.json")

    summary = {
        "run_dir": str(run_dir),
        "manifest": manifest,
        "config": config,
        "main_agent": main_summary.get("summary", {}).get("main_agent", main_summary.get("main_agent", {})),
        "delm_lite": delm_summary.get("summary", {}).get("delm_lite", delm_summary.get("delm_lite", {})),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

