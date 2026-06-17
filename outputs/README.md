# Outputs Index

This directory stores experiment inputs, structured run outputs, and archived legacy results.

## Root Layout

The `outputs/` root should remain small:

- `outputs/amo_parser_ids.txt`: parser-gradeable AMO-P ID list.
- `outputs/amo_description_ids.txt`: description-type AMO ID list.
- `outputs/runs/`: structured outputs for new experiments.
- `outputs/archive/`: archived legacy flat outputs.
- `outputs/cache/`: non-final cache files.

Do not write new experiment result files directly into `outputs/`.

## Structured Runs

New benchmark outputs should use:

```text
outputs/runs/<run_id>/
  manifest.json
  config.json
  sc3/
    predictions.jsonl
    api_errors.jsonl
    analysis_cases.jsonl
    analysis.json
    analysis.md
  repair/
    main_agent/
      results.jsonl
      summary.json
      report.md
      api_errors.jsonl
    delm_lite/
      results.jsonl
      summary.json
      report.md
      api_errors.jsonl
  compare/
  logs/
```

## Archived Legacy Outputs

- `outputs/archive/legacy_<timestamp>/`: archived AMO-P flat output files such as `amo_parser_sc3.jsonl`, `feedback_repair_benchmark.jsonl`, selector failure reports, and verify-then-select diagnostics.
- `outputs/archive/math500_legacy/`: historical MATH-500 pilot outputs.
- `outputs/archive/misc_<timestamp>/`: older backups or provider-specific output snapshots.

Archived result files are preserved locally for provenance and are ignored by Git except archive README files.

## File Types

- `*.jsonl`: per-question detailed records.
- `summary.json`: compact numeric summaries.
- `report.md` / `analysis.md`: Markdown reports for writeups.
- `api_errors.jsonl`: API/network/service error logs; may be empty or absent.

## Archive Tool

Use dry-run first:

```bash
python scripts/analyze/archive_legacy_outputs.py --dry-run
```

Apply only after reviewing the move plan:

```bash
python scripts/analyze/archive_legacy_outputs.py --apply
```
