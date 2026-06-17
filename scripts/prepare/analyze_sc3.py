from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for AMO SC3 analysis.")
    parser.add_argument("--run-dir", default=None, help="Structured run directory.")
    args, unknown = parser.parse_known_args()
    if unknown:
        print("[warning] ignoring unknown arguments:", " ".join(unknown))

    module = importlib.import_module("scripts.legacy.amo_legacy.analyze_sc3_amo_parser")
    if args.run_dir:
        sc3_dir = Path(args.run_dir) / "sc3"
        sc3_dir.mkdir(parents=True, exist_ok=True)
        module.SC3_PATH = sc3_dir / "predictions.jsonl"
        module.OUT_CASES_JSONL = sc3_dir / "analysis_cases.jsonl"
        module.OUT_JSON = sc3_dir / "analysis.json"
        module.OUT_MD = sc3_dir / "analysis.md"
        module.OUT_CASES_CSV = sc3_dir / "analysis_cases.csv"

    module.main()


if __name__ == "__main__":
    main()
