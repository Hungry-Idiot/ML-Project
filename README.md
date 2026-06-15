# Math-DeLM Course Project

This repository contains a course project on multi-agent mathematical reasoning inspired by DeLM-style shared context. The project studies whether lightweight shared-context mechanisms can improve final-answer mathematical problem solving on hard olympiad-style benchmarks.

The current main benchmark is **AMO-Bench-P**, the parser-based subset of AMO-Bench. The project initially used MATH-500 as a pilot benchmark, but MATH-500 quickly became too easy for distinguishing the proposed methods. The main experiments therefore moved to AMO-Bench-P, which better exposes failures of simple voting, answer clustering, and verification-based selection.

## Documentation Index

- Experiment log: [docs/EXPERIMENT_LOG.md](docs/EXPERIMENT_LOG.md)
- Results summary: [docs/RESULTS_SUMMARY.md](docs/RESULTS_SUMMARY.md)
- Next experiment plan: [docs/NEXT_EXPERIMENT_PLAN.md](docs/NEXT_EXPERIMENT_PLAN.md)
- Scripts index: [scripts/README.md](scripts/README.md)
- Outputs index: [outputs/README.md](outputs/README.md)

## Project Goal

The goal is not to fully reproduce DeLM's asynchronous task-queue architecture. Instead, this project explores a lightweight DeLM-inspired framework for mathematical reasoning.

The central idea is:

> Instead of only sampling multiple independent solutions and voting at the end, agents should communicate through compact shared context such as verified answer clusters, candidate clusters, or verification notes.

The project currently investigates three questions:

1. Does self-consistency improve over single-sample reasoning on hard math problems?
2. Can answer-equivalence clustering improve over raw string voting?
3. Does shared context help, or can it amplify wrong answers when the shared context is not actually verified?

## Current Benchmark

The current benchmark is:

```text
AMO-Bench-P
```

Expected local data file:

```text
data/AMO-Bench/test.jsonl
```

The JSONL file is expected to contain records with fields similar to:

```text
id
question_id
problem
gold
solution
answer_type
```

The parser-based subset contains 39 problems:

```text
number: 34
set: 3
variable: 2
```

The 11 `description`-type problems are currently excluded because they require natural-language grading or an LLM judge.

The generated ID files are:

```text
outputs/amo_parser_ids.txt
outputs/amo_description_ids.txt
```

## Main Results So Far

Current results on the 39 AMO-P parser-based problems:

| Method             |                         Scope |         Result | Interpretation                                                                 |
| ------------------ | ----------------------------: | -------------: | ------------------------------------------------------------------------------ |
| Single-CoT         |             39 AMO-P problems |  4/39 = 10.26% | Single-sample reasoning is weak on AMO-P.                                      |
| SC3-RawVote        |             39 AMO-P problems |  7/39 = 17.95% | Self-consistency improves over Single-CoT.                                     |
| Oracle@3           |             39 AMO-P problems | 11/39 = 28.21% | Correct answers sometimes appear among samples but are not selected.           |
| SC3-EquivCluster   |             39 AMO-P problems |  7/39 = 17.95% | Mathematical equivalence clustering does not improve over raw voting on AMO-P. |
| Answer-Cluster-v1  |             39 AMO-P problems |   3/39 = 7.69% | Naive shared candidate clusters can amplify wrong answers.                     |
| Selector-on-SC3    |             39 AMO-P problems |  7/39 = 17.95% | Direct cluster selection does not outperform RawVote.                          |
| Verify-then-Select | 4 oracle-gap diagnostic cases |  1/4 recovered | Explicit verification has some potential but is not yet reliable.              |

The most important diagnostic result is:

```text
SC3-RawVote: 7/39
Oracle@3:    11/39
```

This means that in several cases, at least one of the three samples produced the correct answer, but the voting procedure selected a wrong answer.

However, the current DeLM-inspired variants do not yet produce a robust full-benchmark improvement. This is an important finding of the project: simply sharing candidate answers is not enough. Shared context must be reliable and verified; otherwise, it can propagate errors.

## Key Findings

### 1. AMO-P is much harder and more useful than MATH-500 for this project

MATH-500 was useful as an early pilot benchmark, but the results became too saturated. AMO-P exposes more meaningful failures:

* many problems have three different candidate answers;
* majority vote is often wrong;
* some unanimous answers are still wrong;
* equivalence clustering does not solve the main issue.

### 2. Self-consistency helps, but only modestly

SC3-RawVote improves from:

```text
Single-CoT: 4/39
SC3-RawVote: 7/39
```

This confirms that sampling multiple reasoning paths helps, but the improvement is limited.

### 3. Raw disagreement is very common

SC3 analysis found:

```text
Raw disagreement problems: 29/39 = 74.36%
Equivalent-cluster disagreement problems: 28/39 = 71.79%
RawVote wrong but Oracle@3 correct: 4
No majority selected_support <= 1: 18
Majority wrong selected_support >= 2: 19
Unanimous but wrong: 4
```

This shows that AMO-P contains severe candidate-answer conflict. The correct answer is not necessarily the most frequent answer.

### 4. Naive Answer-Cluster can make results worse

Answer-Cluster-v1 allows later agents to see earlier answer clusters. The final answer is selected by support count.

This performed worse than SC3:

```text
Answer-Cluster-v1: 3/39
SC3-RawVote:       7/39
```

This indicates that unverified shared context can amplify wrong answers. Later agents may follow an earlier wrong answer cluster, increasing its support count.

### 5. Direct Selector-on-SC3 does not outperform RawVote

Selector-on-SC3 reads the answer clusters formed from SC3 samples and asks a selector agent to choose the best cluster.

The result remained:

```text
Selector-on-SC3: 7/39
SC3-RawVote:     7/39
```

The selector did not recover any RawVote failures.

### 6. Verify-then-Select has limited diagnostic value

Verify-then-Select was tested only on the four oracle-gap cases where:

```text
Oracle@3 correct = True
RawVote correct = False
Old Selector correct = False
```

It recovered one of four cases.

This suggests that explicit verification is a promising direction, but the current LLM verifier is unreliable. In some cases, it rejects both correct and incorrect candidates; in other cases, it accepts a wrong answer with high confidence.

## Repository Structure

Recommended active structure:

```text
ML-Project/
  README.md
  requirements.txt
  .env.example
  .gitignore

  scripts/
    utils/
      __init__.py
      io_utils.py
      math_utils.py
      llm_utils.py
      cluster_utils.py
      report_utils.py

    check_amo_data.py
    make_amo_parser_ids.py
    run_single_amo.py
    run_sc3_amo_parser.py
    analyze_sc3_amo_parser.py
    run_answer_cluster_amo_parser.py
    run_selector_on_sc3_amo_parser.py
    inspect_selector_failure_cases.py
    run_verify_then_select_on_oracle_gap.py

  outputs/
    amo_parser_ids.txt
    amo_description_ids.txt
    amo_parser_single.jsonl
    amo_parser_sc3.jsonl
    amo_parser_answer_cluster.jsonl
    amo_parser_selector_on_sc3.jsonl
    amo_parser_sc3_analysis.md
    amo_parser_sc3_analysis.json
    amo_parser_sc3_analysis_cases.jsonl
    selector_failure_cases.md
    selector_failure_cases.jsonl
    verify_then_select_on_oracle_gap.jsonl
    verify_then_select_on_oracle_gap_report.md

  scripts/math500_legacy/
    old MATH-500 pilot scripts
```

The `data/` directory is ignored by Git and should be created locally.

## Utility Modules

Shared utility functions are organized under:

```text
scripts/utils/
```

### `io_utils.py`

Provides:

```python
read_jsonl
write_jsonl
append_jsonl
read_ids
load_done_ids
```

### `math_utils.py`

Provides:

```python
normalize_answer
extract_boxed
safe_verify
equivalent
```

These functions use `math_verify` for mathematical answer checking.

### `llm_utils.py`

Provides:

```python
get_model_name
get_client
response_usage_to_dict
call_chat_completion
call_llm_final_only
```

The `.env` file is loaded only when LLM configuration is needed.

### `cluster_utils.py`

Provides:

```python
choose_raw_majority
cluster_answers
choose_from_clusters
cluster_to_text
```

The `cluster_answers` function uses mathematical equivalence rather than raw string equality.

### `report_utils.py`

Provides:

```python
pct
short_text
tail_text
md_table
```

## Environment Setup

Create and activate a Python environment:

```bash
conda create -n mathdelm python=3.11 -y
conda activate mathdelm
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If parquet conversion is needed, install `pyarrow` as well:

```bash
pip install pyarrow
```

## API Configuration

Create a local `.env` file:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=your_base_url_here
MODEL_NAME=your_model_name_here
```

Do not commit `.env`.

The recommended model for the current experiments is a non-hidden-reasoning chat model, such as `deepseek-chat` or an equivalent OpenAI-compatible model. Earlier reasoning-heavy models caused long hidden reasoning, `finish_reason=length`, or gateway timeout issues.

## Data Preparation

The local data file should be:

```text
data/AMO-Bench/test.jsonl
```

Check the dataset:

```bash
python scripts/check_amo_data.py
```

Generate parser-based AMO-P IDs:

```bash
python scripts/make_amo_parser_ids.py
```

Expected output:

```text
outputs/amo_parser_ids.txt
outputs/amo_description_ids.txt
```

## Running Experiments

### 1. Single-CoT baseline

```bash
python scripts/run_single_amo.py
```

Output:

```text
outputs/amo_parser_single.jsonl
```

### 2. SC3-RawVote baseline

Small test:

```bash
SC3_LIMIT=3 AMO_SC3_MAX_TOKENS=8192 python scripts/run_sc3_amo_parser.py
```

Full run:

```bash
AMO_SC3_MAX_TOKENS=8192 python scripts/run_sc3_amo_parser.py
```

Output:

```text
outputs/amo_parser_sc3.jsonl
```

### 3. Analyze SC3 results

```bash
python scripts/analyze_sc3_amo_parser.py
```

Outputs:

```text
outputs/amo_parser_sc3_analysis.md
outputs/amo_parser_sc3_analysis.json
outputs/amo_parser_sc3_analysis_cases.jsonl
outputs/amo_parser_sc3_analysis_cases.csv
```

### 4. Answer-Cluster-v1

Small test:

```bash
AC_LIMIT=3 AMO_AC_MAX_TOKENS=8192 python scripts/run_answer_cluster_amo_parser.py
```

Full run:

```bash
AMO_AC_MAX_TOKENS=8192 python scripts/run_answer_cluster_amo_parser.py
```

Output:

```text
outputs/amo_parser_answer_cluster.jsonl
```

### 5. Selector-on-SC3

Small test:

```bash
SELECTOR_LIMIT=3 SELECTOR_MAX_TOKENS=4096 python scripts/run_selector_on_sc3_amo_parser.py
```

Full run:

```bash
SELECTOR_MAX_TOKENS=4096 python scripts/run_selector_on_sc3_amo_parser.py
```

Output:

```text
outputs/amo_parser_selector_on_sc3.jsonl
```

### 6. Inspect selector failure cases

```bash
python scripts/inspect_selector_failure_cases.py
```

Outputs:

```text
outputs/selector_failure_cases.md
outputs/selector_failure_cases.jsonl
outputs/selector_failure_cases.csv
```

### 7. Verify-then-Select on oracle-gap cases

Small test:

```bash
VTS_LIMIT=1 VTS_MAX_TOKENS=4096 python scripts/run_verify_then_select_on_oracle_gap.py
```

Full diagnostic run:

```bash
VTS_MAX_TOKENS=4096 python scripts/run_verify_then_select_on_oracle_gap.py
```

Optional repeated verifier run:

```bash
VTS_VERIFIER_REPEATS=2 VTS_MAX_TOKENS=4096 python scripts/run_verify_then_select_on_oracle_gap.py
```

Outputs:

```text
outputs/verify_then_select_on_oracle_gap.jsonl
outputs/verify_then_select_on_oracle_gap_report.md
```

## Recommended Current Workflow

The current recommended workflow is:

```bash
python scripts/check_amo_data.py
python scripts/make_amo_parser_ids.py
python scripts/run_single_amo.py
python scripts/run_sc3_amo_parser.py
python scripts/analyze_sc3_amo_parser.py
python scripts/run_answer_cluster_amo_parser.py
python scripts/run_selector_on_sc3_amo_parser.py
python scripts/inspect_selector_failure_cases.py
python scripts/run_verify_then_select_on_oracle_gap.py
```

Before rerunning expensive API experiments, remove only the specific output file you want to regenerate.

For example:

```bash
rm -f outputs/amo_parser_sc3.jsonl
AMO_SC3_MAX_TOKENS=8192 python scripts/run_sc3_amo_parser.py
```

Do not delete all outputs unless intentionally rebuilding the entire experiment.

## Current Interpretation

The current project should not claim that Answer-Cluster or DELM-lite significantly improves AMO-P accuracy.

A fair interpretation is:

1. SC3 improves over Single-CoT.
2. Oracle@3 reveals that answer selection is a bottleneck.
3. Equivalence clustering alone does not solve the bottleneck.
4. Naive shared answer clusters can amplify wrong answers.
5. Direct selector agents do not reliably improve over RawVote.
6. Verify-then-Select has some diagnostic potential but is not yet robust.
7. A stronger conservative verification strategy is needed for a fair full-benchmark improvement.

## Next Planned Experiment

The next planned experiment is:

```text
Conservative DELM-lite on low-confidence SC3 cases
```

Proposed rule:

```text
If SC3 selected_support >= 2:
    keep SC3-RawVote answer.

If SC3 selected_support <= 1:
    run Verify-then-Select.
```

This avoids changing high-confidence majority answers and only applies expensive verification to low-confidence cases.

Suggested future script:

```text
scripts/run_conservative_vts_on_sc3.py
```

Goal:

```text
SC3-RawVote + verification only on low-confidence cases
```

This is the most promising next step for obtaining a fair full-benchmark improvement.

## Notes on MATH-500 Pilot

Older MATH-500 experiments are preserved as pilot work. They helped validate:

* answer extraction from `\boxed{...}`;
* automatic verification with `math-verify`;
* simple Single-CoT and SC3 pipelines;
* early answer clustering ideas.

However, MATH-500 is no longer the main benchmark because it was not difficult enough to expose differences between methods.

Legacy scripts should be kept under:

```text
scripts/math500_legacy/
```

or eventually moved to:

```text
archive/math500_pilot/
```

## Git and Safety Notes

Do not commit:

```text
.env
data/
__pycache__/
.cache/
large raw datasets
API error logs unless explicitly needed
```

Before committing:

```bash
git status --short
git diff --stat
```

Recommended commit messages:

```bash
git commit -m "Refactor shared utilities for AMO-P experiments"
git commit -m "Update README for AMO-P experiments"
git commit -m "Add conservative DELM-lite experiment"
```

## Current Status Summary

The project is currently in an exploratory stage.

The strongest positive result so far is:

```text
Single-CoT:  4/39
SC3-RawVote: 7/39
```

The strongest diagnostic insight is:

```text
Oracle@3: 11/39
```

This shows that correct answers are sometimes generated but not selected.

The strongest negative finding is:

```text
Answer-Cluster-v1: 3/39
```

This shows that naive shared candidate context can hurt performance.

The next step is to test a conservative verification-based method that only intervenes on low-confidence SC3 cases.
