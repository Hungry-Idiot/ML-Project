# Scripts Index

This directory contains AMO-P experiment scripts, analysis scripts, repair prototypes, legacy MATH-500 pilot scripts, and shared utilities. Scripts are intentionally left in place to avoid breaking relative paths.

## Conventions

- Run commands from the repository root.
- Do not run API-calling scripts without checking their `*_LIMIT`, max-token, sleep, and retry environment variables.
- New experiments should reuse `scripts/utils/` for JSONL I/O, math verification, LLM calls, answer clustering, and report formatting.
- New experiment outputs should normally include three artifacts: detailed `jsonl`, `summary.json`, and `report.md`.

## Data Preparation

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/check_amo_data.py` | Inspect AMO-Bench fields and answer-type distribution. | `data/AMO-Bench/test.jsonl` | Console summary | `python scripts/check_amo_data.py` | Active utility |
| `scripts/make_amo_parser_ids.py` | Split parser-gradeable IDs from description-type IDs. | `data/AMO-Bench/test.jsonl` | `outputs/amo_parser_ids.txt`, `outputs/amo_description_ids.txt` | `python scripts/make_amo_parser_ids.py` | Active utility |
| `scripts/prepare_amo.py` | AMO data preparation helper. | AMO data files | Prepared AMO records | `python scripts/prepare_amo.py` | Utility; inspect before rerun |

## Baseline Experiments

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/run_single_amo.py` | Run Single-CoT on AMO-P parser subset. | `data/AMO-Bench/test.jsonl`, `outputs/amo_parser_ids.txt` | `outputs/amo_parser_single.jsonl` | `AMO_MAX_TOKENS=16000 python scripts/run_single_amo.py` | Active; API-calling |
| `scripts/run_sc3_amo_parser.py` | Run 3-sample self-consistency with raw majority vote. | AMO data and parser IDs | `outputs/amo_parser_sc3.jsonl` | `SC3_LIMIT=3 python scripts/run_sc3_amo_parser.py` | Active; API-calling |
| `scripts/analyze_results.py` | Generic result analyzer for JSONL outputs. | Experiment JSONL | Console summary | `python scripts/analyze_results.py` | Utility; older generic analyzer |

## SC3 Analysis

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/analyze_sc3_amo_parser.py` | Analyze SC3, Single-CoT, Oracle@3, and equivalence clusters. | `outputs/amo_parser_sc3.jsonl`, `outputs/amo_parser_single.jsonl` | `outputs/amo_parser_sc3_analysis.json`, cases JSONL/CSV, Markdown report | `python scripts/analyze_sc3_amo_parser.py` | Active; no API |

## Cluster / Selector Experiments

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/run_answer_cluster_amo_parser.py` | Run naive shared answer-cluster agents. | AMO data and parser IDs | `outputs/amo_parser_answer_cluster.jsonl` | `AC_LIMIT=3 python scripts/run_answer_cluster_amo_parser.py` | Active diagnostic; API-calling |
| `scripts/run_selector_on_sc3_amo_parser.py` | Ask selector to choose among SC3 candidate clusters. | `outputs/amo_parser_sc3.jsonl` | `outputs/amo_parser_selector_on_sc3.jsonl` | `SELECTOR_LIMIT=3 python scripts/run_selector_on_sc3_amo_parser.py` | Active diagnostic; API-calling |
| `scripts/inspect_selector_failure_cases.py` | Build detailed oracle-gap failure-case report. | SC3 analysis and selector outputs | `outputs/selector_failure_cases.*` | `python scripts/inspect_selector_failure_cases.py` | Active diagnostic; no API |

## Verification Experiments

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/run_verify_then_select_on_oracle_gap.py` | Run verifier and final selector on oracle-gap cases. | `outputs/selector_failure_cases.jsonl` | `outputs/verify_then_select_on_oracle_gap.jsonl`, report | `VTS_LIMIT=1 python scripts/run_verify_then_select_on_oracle_gap.py` | Active diagnostic; API-calling |

## Conservative Admission Experiments

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/run_conservative_vts_on_sc3.py` | Run conservative verifier-selector on low-confidence SC3 cases. | `outputs/amo_parser_sc3_analysis_cases.jsonl` | `outputs/conservative_vts_on_sc3.*` | `CVTS_LIMIT=1 python scripts/run_conservative_vts_on_sc3.py` | Active; API-calling |
| `scripts/apply_strict_admission_on_cvts.py` | Apply strict non-API admission policies to Conservative VTS records. | `outputs/conservative_vts_on_sc3.jsonl` | `outputs/strict_admission_on_cvts.*` | `python scripts/apply_strict_admission_on_cvts.py` | Active; no API |
| `scripts/run_pairwise_override_on_changed_cases.py` | Pairwise verifier for Conservative VTS changed cases. | `outputs/conservative_vts_on_sc3.jsonl` | `outputs/pairwise_override_on_changed_cases.*`, `outputs/pairwise_override_final.jsonl` | `PAIRWISE_LIMIT=1 python scripts/run_pairwise_override_on_changed_cases.py` | Active; API-calling |
| `scripts/run_type_aware_vts_on_low_conf.py` | Type-aware verifier for low-confidence SC3 cases. | `outputs/amo_parser_sc3_analysis_cases.jsonl` | `outputs/type_aware_vts_on_low_conf.*` | `TYPE_VTS_LIMIT=1 python scripts/run_type_aware_vts_on_low_conf.py` | Active; API-calling |

## Repair Experiments

| Script | Purpose | Input | Output | Typical command | Status |
| --- | --- | --- | --- | --- | --- |
| `scripts/run_vcr_repair_on_low_conf.py` | Compare Main-Agent Repair and DELM-lite Verified Context Repair. | `outputs/type_aware_vts_on_low_conf.jsonl` | Planned `outputs/vcr_repair_on_low_conf.*` | `VCR_LIMIT=1 python scripts/run_vcr_repair_on_low_conf.py` | Script exists; output artifacts not present in current checkout |
| `scripts/run_feedback_repair_benchmark.py` | Planned oracle-feedback iterative repair benchmark. | Planned low-confidence/oracle-gap cases | Planned benchmark JSONL, summary, report | Not implemented | Planned only; do not create until explicitly requested |

## Utilities

| Path | Purpose | Status |
| --- | --- | --- |
| `scripts/utils/io_utils.py` | JSONL and ID-file helpers. | Shared utility; avoid duplicating. |
| `scripts/utils/math_utils.py` | `math_verify` parsing, equivalence, boxed-answer extraction. | Shared utility; do not change logic casually. |
| `scripts/utils/llm_utils.py` | OpenAI-compatible client and chat-completion wrappers. | Shared utility; handles `.env` at call time. |
| `scripts/utils/cluster_utils.py` | Raw majority voting and math-equivalence clustering. | Shared utility. |
| `scripts/utils/report_utils.py` | Percent formatting, text truncation, Markdown tables. | Shared utility. |
| `scripts/utils.py` | Older flat utility module. | Legacy compatibility; prefer `scripts/utils/`. |

## Legacy Scripts

`scripts/math500_legacy/` contains historical MATH-500 pilot scripts and inspection helpers. They are retained for provenance. Do not delete them during AMO-P cleanup.
