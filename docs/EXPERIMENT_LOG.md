# Experiment Log

This log indexes the AMO-P experiment line without moving or rewriting existing scripts. It is a factual map of the current project state and does not change any experimental result.

## Core Results

| Method | Scope | Result | Interpretation |
| --- | --- | --- | --- |
| Single-CoT | 39 AMO-P parser problems | 4/39 = 10.26% | Single-sample reasoning is weak on AMO-P. |
| SC3-RawVote | 39 AMO-P parser problems | 7/39 = 17.95% | Multi-agent sampling improves over Single-CoT. |
| Oracle@3 | 39 AMO-P parser problems | 11/39 = 28.21% | Correct answers sometimes appear among samples but are not selected. |
| Answer-Cluster-v1 | 39 AMO-P parser problems | 3/39 = 7.69% | Naive shared answer context can amplify wrong answers. |
| Selector-on-SC3 | 39 AMO-P parser problems | 7/39 = 17.95% | Direct selector did not outperform RawVote. |
| Conservative VTS | 39 AMO-P parser problems | 7/39 = 17.95% | Conservative verification did not improve final accuracy. |
| Pairwise Override | 39 AMO-P parser problems | 7/39 = 17.95% | Pairwise override gate prevented changes but did not improve accuracy. |
| Type-aware VTS | 39 AMO-P parser problems | 7/39 = 17.95% | Type-aware verifier did not improve final accuracy. |
| Main-Agent Repair | 39 AMO-P parser problems | 5/39 = 12.82% | Centralized repair is less stable than RawVote and VCR. |
| DELM-lite VCR | 39 AMO-P parser problems | 7/39 = 17.95% | VCR is more robust than Main-Agent Repair but does not beat RawVote. |

Current conclusion: DeLM-inspired methods have not improved final solving accuracy over SC3-RawVote. VCR is nevertheless more robust than Main-Agent Repair because it avoids centralized repair overwriting correct or stable shared context.

## Stage Index

| Stage | Script | Input | Output | Scope | Result | Interpretation | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Stage 0: Data / parser preparation | `scripts/check_amo_data.py` | `data/AMO-Bench/test.jsonl` | Console summary | AMO-Bench test file | 50 total examples; parser subset is 39 problems | Confirms `number`, `set`, and `variable` are parser-gradeable | Active utility |
| Stage 0: Data / parser preparation | `scripts/make_amo_parser_ids.py` | `data/AMO-Bench/test.jsonl` | `outputs/amo_parser_ids.txt`, `outputs/amo_description_ids.txt` | AMO parser vs description split | 39 parser IDs, 11 description IDs | Defines the main AMO-P benchmark subset | Active utility |
| Stage 1: Baselines | `scripts/run_single_amo.py` | `data/AMO-Bench/test.jsonl`, `outputs/amo_parser_ids.txt` | `outputs/amo_parser_single.jsonl` | 39 AMO-P parser problems | 4/39 = 10.26% | Single-CoT baseline | Active result |
| Stage 1: Baselines | `scripts/run_sc3_amo_parser.py` | `data/AMO-Bench/test.jsonl`, `outputs/amo_parser_ids.txt` | `outputs/amo_parser_sc3.jsonl`, optional `outputs/amo_parser_sc3_api_errors.jsonl` | 39 AMO-P parser problems | 7/39 = 17.95% | Self-consistency improves over Single-CoT | Active result |
| Stage 1: Baselines | `scripts/analyze_sc3_amo_parser.py` | `outputs/amo_parser_sc3.jsonl`, `outputs/amo_parser_single.jsonl` | `outputs/amo_parser_sc3_analysis.json`, `outputs/amo_parser_sc3_analysis_cases.jsonl`, `outputs/amo_parser_sc3_analysis.md`, `outputs/amo_parser_sc3_analysis_cases.csv` | 39 AMO-P parser problems | Oracle@3 is 11/39 = 28.21% | Shows selection gap between candidate generation and final choice | Active analysis |
| Stage 2: Naive shared context / clustering | `scripts/run_answer_cluster_amo_parser.py` | `data/AMO-Bench/test.jsonl`, `outputs/amo_parser_ids.txt` | `outputs/amo_parser_answer_cluster.jsonl`, optional `outputs/amo_parser_answer_cluster_api_errors.jsonl` | 39 AMO-P parser problems | 3/39 = 7.69% | Unverified shared clusters can make performance worse | Active diagnostic |
| Stage 2: Naive shared context / clustering | `scripts/run_selector_on_sc3_amo_parser.py` | `outputs/amo_parser_sc3.jsonl` | `outputs/amo_parser_selector_on_sc3.jsonl`, optional `outputs/amo_parser_selector_on_sc3_api_errors.jsonl` | 39 AMO-P parser problems | 7/39 = 17.95% | Selector did not recover RawVote failures | Active diagnostic |
| Stage 2: Naive shared context / clustering | `scripts/inspect_selector_failure_cases.py` | `outputs/amo_parser_sc3_analysis_cases.jsonl`, `outputs/amo_parser_selector_on_sc3.jsonl` | `outputs/selector_failure_cases.jsonl`, `outputs/selector_failure_cases.csv`, `outputs/selector_failure_cases.md` | 4 oracle-gap cases | 4 RawVote-missed-Oracle cases identified | Provides cases for focused repair experiments | Active diagnostic |
| Stage 3: Verification diagnostics | `scripts/run_verify_then_select_on_oracle_gap.py` | `outputs/selector_failure_cases.jsonl` | `outputs/verify_then_select_on_oracle_gap.jsonl`, `outputs/verify_then_select_on_oracle_gap_report.md` | Oracle-gap diagnostic cases | Diagnostic, not full benchmark | Explicit verification has limited reliability | Active diagnostic |
| Stage 4: Conservative DeLM-lite diagnostics | `scripts/run_conservative_vts_on_sc3.py` | `outputs/amo_parser_sc3_analysis_cases.jsonl` | `outputs/conservative_vts_on_sc3.jsonl`, `outputs/conservative_vts_on_sc3_summary.json`, `outputs/conservative_vts_on_sc3_report.md` | 39 AMO-P parser problems | 7/39 = 17.95% | Conservative VTS changed some decisions but did not improve accuracy | Active result |
| Stage 4: Conservative DeLM-lite diagnostics | `scripts/apply_strict_admission_on_cvts.py` | `outputs/conservative_vts_on_sc3.jsonl` | `outputs/strict_admission_on_cvts.jsonl`, `outputs/strict_admission_on_cvts_summary.json`, `outputs/strict_admission_on_cvts_report.md` | 39 AMO-P parser problems | 7/39 = 17.95% | Stricter admission gates avoid unsafe overrides but do not improve accuracy | Active result |
| Stage 4: Conservative DeLM-lite diagnostics | `scripts/run_pairwise_override_on_changed_cases.py` | `outputs/conservative_vts_on_sc3.jsonl` | `outputs/pairwise_override_on_changed_cases.jsonl`, `outputs/pairwise_override_final.jsonl`, `outputs/pairwise_override_on_changed_cases_summary.json`, `outputs/pairwise_override_on_changed_cases_report.md` | 39 AMO-P parser problems | 7/39 = 17.95% | Pairwise gate allowed no beneficial overrides | Active result |
| Stage 4: Conservative DeLM-lite diagnostics | `scripts/run_type_aware_vts_on_low_conf.py` | `outputs/amo_parser_sc3_analysis_cases.jsonl` | `outputs/type_aware_vts_on_low_conf.jsonl`, `outputs/type_aware_vts_on_low_conf_summary.json`, `outputs/type_aware_vts_on_low_conf_report.md` | 39 AMO-P parser problems | 7/39 = 17.95% | Type-aware verification did not solve RawVote-wrong cases | Active result |
| Stage 5: Verified Context Repair | `scripts/run_vcr_repair_on_low_conf.py` | `outputs/type_aware_vts_on_low_conf.jsonl` | Planned outputs: `outputs/vcr_repair_on_low_conf.jsonl`, `outputs/vcr_repair_on_low_conf_summary.json`, `outputs/vcr_repair_on_low_conf_report.md` | 39 AMO-P parser problems | Main-Agent Repair: 5/39 = 12.82%; DELM-lite VCR: 7/39 = 17.95% | VCR is more stable than Main-Agent Repair but does not improve over RawVote | Script exists; VCR output artifacts are not present in this checkout |
| Stage 6: Next planned experiment | `scripts/run_feedback_repair_benchmark.py` | Planned: AMO-P low-confidence / oracle-gap cases | Planned: jsonl, summary JSON, report Markdown | Oracle-feedback iterative repair benchmark | Not implemented | Compare iterative repair efficiency under bounded oracle feedback | Planned only |

## Notes

- `scripts/run_feedback_repair_benchmark.py` is intentionally not created yet.
- Existing raw outputs remain in `outputs/`; this log is an index, not a replacement for raw records.
- API error logs are operational artifacts and may be empty or absent depending on the run.
