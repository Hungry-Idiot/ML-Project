from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.math_delm.evaluation.compare import compare_method_summaries


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Main-Agent and DELM-lite summary files.")
    parser.add_argument("--main", required=True, help="Path to main_agent/summary.json")
    parser.add_argument("--delm", required=True, help="Path to delm_lite/summary.json")
    parser.add_argument("--output", required=True, help="Output directory for comparison files")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    comparison = compare_method_summaries(load_json(Path(args.main)), load_json(Path(args.delm)))
    (output_dir / "main_vs_delm.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    main = comparison["main_agent"]
    delm = comparison["delm_lite"]
    lines = [
        "# Main-Agent vs DELM-lite",
        "",
        "| metric | main_agent | delm_lite | delta |",
        "|---|---:|---:|---:|",
        f"| solved | {main.get('solved', 0)} | {delm.get('solved', 0)} | {comparison['delm_minus_main_solved']} |",
        f"| api_calls | {main.get('api_calls', 0)} | {delm.get('api_calls', 0)} | {comparison['delm_minus_main_api_calls']} |",
        f"| total_tokens | {main.get('total_tokens', 0)} | {delm.get('total_tokens', 0)} | {comparison['delm_minus_main_tokens']} |",
        "",
    ]
    (output_dir / "main_vs_delm.md").write_text("\n".join(lines), encoding="utf-8")
    print("Saved:", output_dir / "main_vs_delm.json")
    print("Saved:", output_dir / "main_vs_delm.md")


if __name__ == "__main__":
    main()

