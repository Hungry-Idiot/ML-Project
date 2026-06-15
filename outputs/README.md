# Outputs Index

This directory stores raw experiment records, summaries, reports, and operational error logs. Raw JSONL files should not be deleted because they contain per-question details that are expensive to regenerate.

## File Types

- `*.jsonl`: per-question detailed records.
- `*_summary.json`: compact numeric summaries for quick result lookup.
- `*_report.md` or analysis `*.md`: Markdown reports for writeups.
- `*api_errors.jsonl`: API/network/service error logs; these are operational logs and may be empty or absent.

## AMO-P IDs and Baselines

| File | Type | Notes |
| --- | --- | --- |
| `outputs/amo_parser_ids.txt` | Core input | Parser-gradeable AMO-P subset IDs. |
| `outputs/amo_description_ids.txt` | Core input | Description-type AMO IDs excluded from parser grading. |
| `outputs/amo_parser_single.jsonl` | JSONL | Single-CoT detailed results. |
| `outputs/amo_parser_sc3.jsonl` | JSONL | SC3-RawVote sample records and selected answers. |
| `outputs/amo_parser_answer_cluster.jsonl` | JSONL | Answer-Cluster-v1 detailed results. |
| `outputs/amo_parser_selector_on_sc3.jsonl` | JSONL | Selector-on-SC3 detailed results. |

## SC3 Analysis

| File | Type | Notes |
| --- | --- | --- |
| `outputs/amo_parser_sc3_analysis.json` | Summary JSON | Main baseline, Oracle@3, disagreement, and token-use summary. |
| `outputs/amo_parser_sc3_analysis_cases.jsonl` | JSONL | Per-case analysis records. |
| `outputs/amo_parser_sc3_analysis_cases.csv` | CSV | Spreadsheet-friendly case table. |
| `outputs/amo_parser_sc3_analysis.md` | Markdown report | Report-writing reference. |
| `outputs/selector_failure_cases.jsonl` | JSONL | RawVote-missed-Oracle diagnostic cases. |
| `outputs/selector_failure_cases.csv` | CSV | Spreadsheet-friendly failure case table. |
| `outputs/selector_failure_cases.md` | Markdown report | Failure-case report. |

## Verify-then-Select Diagnostics

| File | Type | Notes |
| --- | --- | --- |
| `outputs/verify_then_select_on_oracle_gap.jsonl` | JSONL | Verify-then-select records on oracle-gap cases. |
| `outputs/verify_then_select_on_oracle_gap_report.md` | Markdown report | Diagnostic report. |

## Conservative VTS

| File | Type | Notes |
| --- | --- | --- |
| `outputs/conservative_vts_on_sc3.jsonl` | JSONL | Conservative VTS detailed records. |
| `outputs/conservative_vts_on_sc3_summary.json` | Summary JSON | Quick result summary. |
| `outputs/conservative_vts_on_sc3_report.md` | Markdown report | Report-writing reference. |

## Strict Admission

| File | Type | Notes |
| --- | --- | --- |
| `outputs/strict_admission_on_cvts.jsonl` | JSONL | Strict-admission detailed records. |
| `outputs/strict_admission_on_cvts_summary.json` | Summary JSON | Policy comparison and final summary. |
| `outputs/strict_admission_on_cvts_report.md` | Markdown report | Report-writing reference. |

## Pairwise Override

| File | Type | Notes |
| --- | --- | --- |
| `outputs/pairwise_override_on_changed_cases.jsonl` | JSONL | Pairwise verifier records for changed cases. |
| `outputs/pairwise_override_final.jsonl` | JSONL | Final pairwise override decisions over the benchmark. |
| `outputs/pairwise_override_on_changed_cases_summary.json` | Summary JSON | Quick result summary. |
| `outputs/pairwise_override_on_changed_cases_report.md` | Markdown report | Report-writing reference. |

## Type-aware VTS

| File | Type | Notes |
| --- | --- | --- |
| `outputs/type_aware_vts_on_low_conf.jsonl` | JSONL | Type-aware verifier records. |
| `outputs/type_aware_vts_on_low_conf_summary.json` | Summary JSON | Quick result summary. |
| `outputs/type_aware_vts_on_low_conf_report.md` | Markdown report | Report-writing reference. |

## VCR Repair

The VCR repair script exists at `scripts/run_vcr_repair_on_low_conf.py`, but the following planned artifacts are not present in the current `outputs/` listing:

- `outputs/vcr_repair_on_low_conf.jsonl`
- `outputs/vcr_repair_on_low_conf_summary.json`
- `outputs/vcr_repair_on_low_conf_report.md`

## API Error Logs Present

| File | Notes |
| --- | --- |
| `outputs/amo_parser_answer_cluster_api_errors.jsonl` | Answer-Cluster API error log. |
| `outputs/amo_parser_sc3_api_errors.jsonl` | SC3 API error log. |
| `outputs/amo_parser_selector_on_sc3_api_errors.jsonl` | Selector API error log. |

## Legacy Outputs

`outputs/math500_legacy/` contains historical MATH-500 pilot outputs. Keep these for provenance, but do not treat them as current AMO-P mainline results.
