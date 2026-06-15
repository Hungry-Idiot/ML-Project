# Results Summary

## Main Result Table

| Method | Scope | Result | Notes |
| --- | --- | --- | --- |
| Single-CoT | 39 AMO-P parser problems | 4/39 = 10.26% | Single-sample baseline. |
| SC3-RawVote | 39 AMO-P parser problems | 7/39 = 17.95% | Multi-sample raw majority vote. |
| Oracle@3 | 39 AMO-P parser problems | 11/39 = 28.21% | Upper-bound diagnostic for three samples. |
| Answer-Cluster-v1 | 39 AMO-P parser problems | 3/39 = 7.69% | Naive shared clusters underperform RawVote. |
| Conservative VTS | 39 AMO-P parser problems | 7/39 = 17.95% | Conservative verifier-selection did not improve final accuracy. |
| Pairwise Override | 39 AMO-P parser problems | 7/39 = 17.95% | Override gate did not admit beneficial changes. |
| Type-aware VTS | 39 AMO-P parser problems | 7/39 = 17.95% | Type-aware verifier did not improve final accuracy. |
| Main-Agent Repair | 39 AMO-P parser problems | 5/39 = 12.82% | Centralized repair is less stable than RawVote. |
| DELM-lite VCR | 39 AMO-P parser problems | 7/39 = 17.95% | More robust than Main-Agent Repair, but no RawVote improvement. |

## Honest Interpretation

- Multi-agent sampling improves over Single-CoT.
- DeLM-inspired shared context has not improved final accuracy over SC3-RawVote.
- VCR is more robust than Main-Agent Repair, but does not repair RawVote-wrong cases.
- The next experiment will evaluate iterative repair efficiency under oracle feedback.

## Practical Takeaway

The current evidence does not support claiming that DeLM-style shared context significantly improves final AMO-P accuracy. The strongest positive signal is diagnostic: shared verified context can be safer than centralized repair, but current admission and verification policies are not enough to recover the Oracle@3 gap.
