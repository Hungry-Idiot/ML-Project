from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare.analyze_sc3 import main


if __name__ == "__main__":
    print(
        "[deprecated] scripts/analyze_sc3_amo_parser.py is a compatibility wrapper. "
        "Use scripts/prepare/analyze_sc3.py.",
        file=sys.stderr,
    )
    main()

