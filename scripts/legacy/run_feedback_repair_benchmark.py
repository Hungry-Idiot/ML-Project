from __future__ import annotations

import sys

from src.math_delm.feedback_repair_benchmark import main


if __name__ == "__main__":
    print(
        "[deprecated] scripts/legacy/run_feedback_repair_benchmark.py delegates to "
        "src.math_delm.feedback_repair_benchmark.",
        file=sys.stderr,
    )
    main()

