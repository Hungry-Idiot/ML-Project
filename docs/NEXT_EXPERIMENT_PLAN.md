# Next Experiment Plan: Oracle-feedback Iterative Repair Benchmark

## Motivation

Current AMO-P results show a gap between candidate generation and final selection: SC3-RawVote solves 7/39 problems, while Oracle@3 reaches 11/39. Some correct answers are present among sampled candidates but are not selected. Conservative verification and repair variants have not improved final benchmark accuracy over RawVote, so the next question is whether iterative feedback improves repair efficiency rather than just final one-shot selection.

The proposed benchmark evaluates how quickly different repair strategies recover after being told only that their current answer is incorrect.

## Compared Methods

1. **Main-Agent Feedback Retry**
   - A centralized repair agent receives the problem, the current answer, and minimal oracle feedback.
   - It retries for a fixed number of rounds or until solved.

2. **DELM-lite Feedback Retry**
   - Multiple repair candidates are generated and organized through verified shared context.
   - The method uses compact answer clusters and verification notes instead of a single centralized correction trace.

## Metrics

| Metric | Meaning |
| --- | --- |
| `solved_count` | Number of problems solved within the allowed repair rounds. |
| `solved_rate` | `solved_count / total_cases`. |
| `avg_rounds_to_solve` | Average number of feedback rounds needed for solved cases. |
| `wall_time_per_solved` | Total wall-clock time divided by solved cases. |
| `tokens_per_solved` | Total token usage divided by solved cases. |
| `repeated_wrong_answer_count` | Number of times a method repeats a previously rejected wrong answer. |

## Fairness Controls

- Use a fixed maximum number of repair rounds for both methods.
- Use a fixed API call budget per problem.
- Use the same model, temperature policy, and max-token policy unless explicitly ablated.
- Record token usage for every call when the provider returns usage metadata.
- Record wall-clock time per problem and per solved case.
- Evaluate on the same case set, ideally low-confidence or oracle-gap AMO-P cases.

## Oracle Safety

- The oracle may only say `incorrect` or `correct`.
- The oracle must not reveal the gold answer.
- The oracle must not reveal which candidate cluster is correct.
- The model should not receive hidden solution text.
- Each repair round should record the previous wrong answers so repeated mistakes can be measured.

## Planned Script

```text
scripts/run_feedback_repair_benchmark.py
```

This script is not implemented yet. It should produce:

```text
outputs/feedback_repair_benchmark.jsonl
outputs/feedback_repair_benchmark_summary.json
outputs/feedback_repair_benchmark_report.md
```

## Expected Outcome

The goal is not to assume that DELM-lite will improve final accuracy. The benchmark should measure whether shared verified context makes repair more efficient and less likely to repeat wrong answers under equal feedback and API budgets.
