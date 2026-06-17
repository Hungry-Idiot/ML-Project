# Scripts Index

Run commands from the repository root. New code should live in `src/math_delm/`; scripts should stay as thin CLI entrypoints.

## Recommended Entrypoints

| Script | Purpose | Output Policy | Typical command |
| --- | --- | --- | --- |
| `scripts/prepare/run_sc3_amo.py` | Run AMO SC3 generation. | `outputs/runs/<run_id>/sc3/` when `--run-dir` is provided. | `python scripts/prepare/run_sc3_amo.py --run-dir outputs/runs/test_sc3` |
| `scripts/prepare/analyze_sc3.py` | Analyze AMO SC3 predictions. | `outputs/runs/<run_id>/sc3/` when `--run-dir` is provided. | `python scripts/prepare/analyze_sc3.py --run-dir outputs/runs/test_sc3` |
| `scripts/run/run_feedback_repair.py` | Unified feedback-repair benchmark. | `outputs/runs/<run_id>/repair/...` | `python scripts/run/run_feedback_repair.py --agent both --limit 3 --run-id test_both_3q` |
| `scripts/run/run_main_agent.py` | Main-Agent-only wrapper. | `outputs/runs/<run_id>/repair/main_agent/` | `python scripts/run/run_main_agent.py --limit 3 --run-id test_main_3q` |
| `scripts/run/run_delm_lite.py` | DELM-lite-only wrapper. | `outputs/runs/<run_id>/repair/delm_lite/` | `python scripts/run/run_delm_lite.py --limit 3 --workers 2 --run-id test_delm_3q` |
| `scripts/analyze/compare_runs.py` | Compare two summary files. | User-provided compare directory. | `python scripts/analyze/compare_runs.py --main ... --delm ... --output outputs/runs/compare_test` |
| `scripts/analyze/archive_legacy_outputs.py` | Move known flat legacy outputs into archive. | `outputs/archive/legacy_<timestamp>/` | `python scripts/analyze/archive_legacy_outputs.py --apply` |
| `scripts/analyze/audit_feedback_repair.py` | Audit feedback repair JSONL records. | Console or user-provided output. | `python scripts/analyze/audit_feedback_repair.py --tail 1200` |

## Deprecated Root Wrappers

These files are kept only for compatibility. Do not add new implementation logic here.

- `scripts/run_feedback_repair_benchmark.py`
- `scripts/run_sc3_amo_parser.py`
- `scripts/analyze_sc3_amo_parser.py`

## Legacy Code

- `scripts/legacy/amo_legacy/` contains old AMO baseline, selector, verification, inspection, and preparation scripts.
- `scripts/legacy/run_feedback_repair_benchmark.py` delegates to `src.math_delm.feedback_repair_benchmark`.
- `scripts/math500_legacy/` contains historical MATH-500 pilot scripts.

## Utilities

- `scripts/utils/` is retained for legacy compatibility and shared helpers already used by older scripts.
- New architecture code should prefer `src/math_delm/`.
- Do not duplicate JSONL I/O, LLM calls, equivalence checks, clustering, or report formatting in new scripts.

## Output Rule

New experiment outputs must not be written directly into `outputs/` root. Use `outputs/runs/<run_id>/`.
