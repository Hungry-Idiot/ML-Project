# Current Experiment Results Summary

## Main Results

| Method | Total | Correct | Accuracy | Parse Fail | Parse Success |
| --- | --- | --- | --- | --- | --- |
| Single-CoT full50 | 50 | 46 | 92.00% | 3 | 94.00% |
| Single-CoT valid47 | 47 | 46 | 97.87% | 0 | 100.00% |
| Self-Consistency-3 valid47 | 47 | 47 | 100.00% | 0 | 100.00% |
| Answer-Cluster-DeLM valid47 | 47 | 47 | 100.00% | 0 | 100.00% |
| Naive-DeLM fixed valid18 | 18 | 18 | 100.00% | 0 | 100.00% |


## Answer-Cluster-DeLM Extra Statistics

- Total: 47
- One-cluster problems: 47
- Multi-cluster problems: 0
- Problems with support_count=3: 46
- Raw disagreement but one equivalent cluster: 2
- Problems with support_count not 3: 1


## Notes

- `Single-CoT full50` includes parse failures from the original 50 examples.
- `Single-CoT valid47` filters `single_50.jsonl` by `valid_ids_50.txt`; it removes parse-fail examples but keeps real wrong answers.
- `Self-Consistency-3 valid47` and `Answer-Cluster-DeLM valid47` are compared on the same valid47 subset.
- `Naive-DeLM fixed valid18` is kept as a smaller auxiliary baseline.