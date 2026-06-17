# Project Structure

The current project is organized around a source package plus thin CLI entrypoints. New experiments should write to structured run directories, not to flat files in `outputs/`.

## Recommended Layout

```text
src/math_delm/
  agents/       # Main-Agent and DELM-lite orchestration
  prompts/      # Prompt construction only
  repair/       # parsing, equivalence, verifier, selector, clustering, shared context
  evaluation/   # metrics, reports, run comparison
  io/           # JSONL and run-directory helpers
  llm/          # OpenAI-compatible client wrappers

scripts/
  prepare/      # SC3 generation and analysis entrypoints
  run/          # feedback-repair run entrypoints
  analyze/      # compare, audit, archive utilities
  legacy/       # deprecated AMO implementations and compatibility code
  math500_legacy/
  utils/        # shared legacy utilities still used by old scripts

outputs/
  runs/         # new structured experiment runs
  archive/      # archived flat legacy outputs
  cache/        # non-final cache files
```

## Recommended Entrypoints

| Task | Command |
| --- | --- |
| Run SC3 AMO generation | `python scripts/prepare/run_sc3_amo.py --run-dir outputs/runs/<run_id>` |
| Analyze SC3 AMO results | `python scripts/prepare/analyze_sc3.py --run-dir outputs/runs/<run_id>` |
| Run feedback repair | `python scripts/run/run_feedback_repair.py --agent main\|delm\|both --run-id <run_id>` |
| Run Main-Agent only | `python scripts/run/run_main_agent.py --run-id <run_id>` |
| Run DELM-lite only | `python scripts/run/run_delm_lite.py --run-id <run_id>` |
| Compare two summaries | `python scripts/analyze/compare_runs.py --main ... --delm ... --output ...` |
| Archive old flat outputs | `python scripts/analyze/archive_legacy_outputs.py --apply` |

## Deprecated Entrypoints

These paths are wrappers only and should not receive new logic:

- `scripts/run_feedback_repair_benchmark.py`
- `scripts/run_sc3_amo_parser.py`
- `scripts/analyze_sc3_amo_parser.py`

Legacy AMO scripts are stored under `scripts/legacy/amo_legacy/`. Historical MATH-500 scripts remain under `scripts/math500_legacy/`.

## Output Policy

New experiment outputs must go under:

```text
outputs/runs/<run_id>/
  manifest.json
  config.json
  sc3/
  repair/
    main_agent/
    delm_lite/
  compare/
  logs/
```

The `outputs/` root should contain only:

- `outputs/README.md`
- `outputs/amo_parser_ids.txt`
- `outputs/amo_description_ids.txt`
- `outputs/runs/`
- `outputs/archive/`
- `outputs/cache/`

Flat legacy result files are preserved under `outputs/archive/legacy_<timestamp>/`.

## Core Inputs

| File | Role |
| --- | --- |
| `data/AMO-Bench/test.jsonl` | Main AMO-Bench data source. |
| `outputs/amo_parser_ids.txt` | Parser-gradeable AMO-P IDs. |
| `outputs/amo_description_ids.txt` | Description-type AMO IDs excluded from parser grading. |
| `.env` | Local API credentials; never print or commit. |
| `.env.example` | Safe environment template. |
| `requirements.txt` | Python dependency list. |

## Regeneration Notes

- Raw JSONL model outputs require API calls and should be preserved.
- Summary JSON and Markdown reports can usually be regenerated from detailed JSONL records.
- `outputs/archive/` is ignored by Git except its README; archived result files are kept locally for provenance.
- `__pycache__/`, `*.pyc`, logs, and cache directories are not source files.
