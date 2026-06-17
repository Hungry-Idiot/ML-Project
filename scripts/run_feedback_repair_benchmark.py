import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.math_delm import config as cfg
from src.math_delm.feedback_repair_benchmark import main


if __name__ == "__main__":
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "Deprecated compatibility entrypoint.\n\n"
            "Runs the legacy environment-variable workflow using LEGACY_* paths.\n"
            "Recommended new entrypoint:\n"
            "  python scripts/run/run_feedback_repair.py --agent main|delm|both --input-cases PATH --run-id RUN_ID\n",
        )
        raise SystemExit(0)

    print(
        "[deprecated] scripts/run_feedback_repair_benchmark.py is now a compatibility "
        "wrapper. Use scripts/run/run_feedback_repair.py for run-directory outputs.",
        file=sys.stderr,
    )
    cfg.INPUT_PATH = cfg.LEGACY_INPUT_PATH
    cfg.OUT_PATH = cfg.LEGACY_OUT_PATH
    cfg.ERROR_PATH = cfg.LEGACY_ERROR_PATH
    cfg.OUT_MD = cfg.LEGACY_OUT_MD
    cfg.OUT_SUMMARY_JSON = cfg.LEGACY_OUT_SUMMARY_JSON
    main()
