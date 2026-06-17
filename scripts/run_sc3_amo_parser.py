from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare.run_sc3_amo import main


if __name__ == "__main__":
    print(
        "[deprecated] scripts/run_sc3_amo_parser.py is a compatibility wrapper. "
        "Use scripts/prepare/run_sc3_amo.py.",
        file=sys.stderr,
    )
    main()

