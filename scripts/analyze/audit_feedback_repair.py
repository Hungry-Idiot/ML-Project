from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    legacy_audit = Path(__file__).resolve().parents[1] / "legacy" / "amo_legacy" / "audit_feedback_repair.py"
    runpy.run_path(str(legacy_audit), run_name="__main__")
