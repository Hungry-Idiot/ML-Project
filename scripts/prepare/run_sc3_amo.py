from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for AMO SC3 generation.")
    parser.add_argument("--run-dir", default=None, help="Structured run directory.")
    args, unknown = parser.parse_known_args()
    if unknown:
        print("[warning] ignoring unknown arguments:", " ".join(unknown))

    module = importlib.import_module("scripts.legacy.amo_legacy.run_sc3_amo_parser")
    if args.run_dir:
        sc3_dir = Path(args.run_dir) / "sc3"
        sc3_dir.mkdir(parents=True, exist_ok=True)
        module.OUT_PATH = sc3_dir / "predictions.jsonl"
        module.ERROR_PATH = sc3_dir / "api_errors.jsonl"

        manifest = Path(args.run_dir) / "manifest.json"
        config = Path(args.run_dir) / "config.json"
        if not manifest.exists():
            manifest.write_text(
                __import__("json").dumps(
                    {
                        "run_id": Path(args.run_dir).name,
                        "dataset": "amo",
                        "agent": "sc3",
                        "model": os.getenv("MODEL_NAME"),
                        "input_files": [str(module.DATA_PATH), str(module.IDS_PATH)],
                        "output_files": [str(module.OUT_PATH), str(module.ERROR_PATH)],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        if not config.exists():
            config.write_text(
                __import__("json").dumps(
                    {
                        "num_samples": module.NUM_SAMPLES,
                        "max_tokens": module.MAX_TOKENS,
                        "temperature": module.TEMPERATURE,
                        "limit": module.LIMIT,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    module.main()


if __name__ == "__main__":
    main()
