from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path


PATTERNS = [
    "amo_parser_*.jsonl",
    "amo_parser_*.json",
    "amo_parser_*.md",
    "amo_parser_*.csv",
    "feedback_repair_*.jsonl",
    "feedback_repair_*.json",
    "feedback_repair_*.md",
    "selector_failure_*.jsonl",
    "selector_failure_*.csv",
    "selector_failure_*.md",
    "verify_then_select_*.jsonl",
    "verify_then_select_*.md",
]

EXCLUDED_NAMES = {"README.md"}
EXCLUDED_DIRS = {"runs", "archive", "cache"}


def find_legacy_outputs(outputs_dir: Path) -> list[Path]:
    paths: set[Path] = set()
    for pattern in PATTERNS:
        for path in outputs_dir.glob(pattern):
            if path.name in EXCLUDED_NAMES:
                continue
            if any(part in EXCLUDED_DIRS for part in path.relative_to(outputs_dir).parts[:-1]):
                continue
            if path.is_file():
                paths.add(path)
    return sorted(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive known flat legacy output files. Dry-run by default.")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--apply", action="store_true", help="Actually move files.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without moving files.")
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = outputs_dir / "archive" / f"legacy_{timestamp}"
    paths = find_legacy_outputs(outputs_dir)

    print("Archive destination:", archive_dir)
    print("Mode:", "apply" if args.apply else "dry-run")
    if not paths:
        print("No known legacy output files found.")
        return

    for path in paths:
        print("MOVE", path, "->", archive_dir / path.name)

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to move these files.")
        return

    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.move(str(path), str(archive_dir / path.name))
    print("Archived", len(paths), "files.")


if __name__ == "__main__":
    main()
