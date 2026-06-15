# AMO-P SC3 Analysis

- Input SC3 file: `outputs/amo_parser_sc3.jsonl`
- Single-CoT file: `outputs/amo_parser_single.jsonl`
- Total problems: **39**

## Main Results
| Method | Correct | Total | Accuracy |
| --- | --- | --- | --- |
| Single-CoT | 4 | 39 | 10.26% |
| SC3-RawVote | 7 | 39 | 17.95% |
| Oracle@3 | 11 | 39 | 28.21% |
| SC3-EquivCluster | 7 | 39 | 17.95% |

## Key Diagnostics
| Metric | Count | Rate |
| --- | --- | --- |
| Raw disagreement problems | 29 | 74.36% |
| Equivalent-cluster disagreement problems | 28 | 71.79% |
| Raw disagreement but one equivalent cluster | 1 | 2.56% |
| RawVote wrong but Oracle@3 correct | 4 | 10.26% |
| EquivCluster correct while RawVote wrong | 0 | 0.00% |
| RawVote correct while EquivCluster wrong | 0 | 0.00% |
| No majority, selected_support <= 1 | 18 | 46.15% |
| Majority wrong, selected_support >= 2 | 19 | 48.72% |
| Unanimous raw answers | 6 | 15.38% |
| Unanimous but wrong | 4 | 10.26% |
| All samples wrong | 27 | 69.23% |
| All samples correct | 2 | 5.13% |

## Single-CoT vs SC3
| Metric | Count | Rate |
| --- | --- | --- |
| SC3 recovers Single-CoT failure | 6 | 15.38% |
| SC3 regresses from Single-CoT success | 3 | 7.69% |
| Oracle@3 recovers Single-CoT failure | 9 | 23.08% |

## RawVote Accuracy by selected_support
| selected_support | Total | Correct | Accuracy |
| --- | --- | --- | --- |
| 0 | 1 | 0 | 0.00% |
| 1 | 17 | 5 | 29.41% |
| 2 | 15 | 0 | 0.00% |
| 3 | 6 | 2 | 33.33% |

## EquivCluster Accuracy by selected_support
| equiv_selected_support | Total | Correct | Accuracy |
| --- | --- | --- | --- |
| 0 | 1 | 0 | 0.00% |
| 1 | 14 | 4 | 28.57% |
| 2 | 17 | 1 | 5.88% |
| 3 | 7 | 2 | 28.57% |

## Accuracy by answer_type
### RawVote
| answer_type | Total | Correct | Accuracy |
| --- | --- | --- | --- |
| number | 34 | 5 | 14.71% |
| set | 3 | 1 | 33.33% |
| variable | 2 | 1 | 50.00% |

### Oracle@3
| answer_type | Total | Correct | Accuracy |
| --- | --- | --- | --- |
| number | 34 | 9 | 26.47% |
| set | 3 | 1 | 33.33% |
| variable | 2 | 1 | 50.00% |

### EquivCluster
| answer_type | Total | Correct | Accuracy |
| --- | --- | --- | --- |
| number | 34 | 5 | 14.71% |
| set | 3 | 1 | 33.33% |
| variable | 2 | 1 | 50.00% |

## Sample Position Accuracy
| Sample ID | Total | Parsed | Parse Success | Correct | Accuracy |
| --- | --- | --- | --- | --- | --- |
| 0 | 39 | 36 | 92.31% | 8 | 20.51% |
| 1 | 39 | 37 | 94.87% | 4 | 10.26% |
| 2 | 39 | 36 | 92.31% | 4 | 10.26% |

## Distributions
### Finish reason, sample-level
| finish_reason | Count |
| --- | --- |
| 'stop' | 109 |
| 'length' | 8 |

### raw_unique_count
| raw_unique_count | Count |
| --- | --- |
| 0 | 1 |
| 1 | 9 |
| 2 | 14 |
| 3 | 15 |

### equiv_cluster_count
| equiv_cluster_count | Count |
| --- | --- |
| 0 | 1 |
| 1 | 10 |
| 2 | 16 |
| 3 | 12 |

## Token Usage
| Metric | Value |
| --- | --- |
| Total sample calls | 117 |
| Total prompt tokens | 38712 |
| Total completion tokens | 497330 |
| Total tokens | 536042 |
| Avg prompt tokens / call | 330.87 |
| Avg completion tokens / call | 4250.68 |
| Avg total tokens / call | 4581.56 |

## Important Case Lists
### RawVote wrong but Oracle@3 correct
Count: **4**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | number | 2 | 2 | \boxed{6} | 7 | 7 | ['6', '7', '7'] |
| 18 | 19 | number | 2 | 2 | \boxed{666} | 703 | 703 | ['666', '703', '703'] |
| 29 | 30 | number | 1 | 1 | \boxed{3736} | 3737 | 3737 | ['3737', '916', '3736'] |
| 35 | 36 | number | 2 | 2 | \boxed{343} | 181 | 181 | ['181', '181', '343'] |

### EquivCluster correct while RawVote wrong
Count: **0**

### SC3 recovers Single-CoT failure
Count: **6**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3 | 4 | number | 1 | 1 | \boxed{512578} | 512578 | 512578 | ['512578', '\\frac{2025}{4}', '\\frac{2025^2}{8}'] |
| 4 | 5 | variable | 1 | 1 | $$\boxed{\dfrac{(2+\sqrt{3})^{2^{2-n}}+(2-\sqrt{3})^{2^{2-n}}}{2}}$$ | a_n = \frac{ (2+\sqrt{3})^{2^{2-n}} + (2-\sqrt{3})^{2^{2-n}} }{2} | a_n = \frac{ (2+\sqrt{3})^{2^{2-n}} + (2-\sqrt{3})^{2^{2-n}} }{2} | ['a_n = \\frac{ (2+\\sqrt{3})^{2^{2-n}} + (2-\\sqrt{3})^{2^{2-n}} }{2}', 'a_n = \\frac{2^{2^{n-1}} + 1}{2^{2^{n-1}} - 1}... |
| 5 | 6 | number | 1 | 1 | \boxed{1382935444} | 1382935444 | 1382935444 | ['1382935444', '4139594096', '1037287350'] |
| 12 | 13 | number | 1 | 2 | \boxed{\frac{33497570861567}{2}} | \frac{33497570861567}{2} | \frac{33497570861567}{2} | ['\\frac{33497570861567}{2}', '16748785430783.5', '2016.6903'] |
| 19 | 20 | number | 3 | 3 | \boxed{120} | 120 | 120 | ['120', '120', '120'] |
| 48 | 49 | number | 1 | 1 | $$ \boxed{16} $$ | 16 | 16 | [None, '16', '145'] |

### SC3 regresses from Single-CoT success
Count: **3**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | number | 2 | 2 | \boxed{6} | 7 | 7 | ['6', '7', '7'] |
| 10 | 11 | number | 2 | 2 | \boxed{10} | 3 | 3 | ['\\infty', '3', '3'] |
| 15 | 16 | number | 1 | 1 | \boxed{68} | 68.04 | 68.04 | ['68.04', '\\frac{1892 - 512\\sqrt{2}}{17}', '60'] |

### Raw disagreement but one equivalent cluster
Count: **1**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 18 | number | 2 | 3 | \boxed{\frac{\sqrt{3}}{45}} | \frac{2}{45} | \frac{2}{45} | ['\\frac{2}{45}', '\\frac{2}{45} \\cos\\frac{\\pi}{4050}', '\\frac{2}{45}'] |

### Unanimous but wrong
Count: **4**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 21 | number | 3 | 3 | \boxed{230} | 104 | 104 | ['104', '104', '104'] |
| 30 | 31 | number | 3 | 3 | \boxed{2295} | 2175 | 2175 | ['2175', '2175', '2175'] |
| 32 | 33 | number | 3 | 3 | \boxed{34} | 51 | 51 | ['51', '51', '51'] |
| 43 | 44 | number | 3 | 3 | \boxed{8281323} | 209774391786 | 209774391786 | ['209774391786', '209774391786', '209774391786'] |

### Majority wrong
Count: **19**
| id | qid | type | raw_sup | eq_sup | gold | raw_selected | eq_selected | pred_answers |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | number | 2 | 2 | \boxed{6} | 7 | 7 | ['6', '7', '7'] |
| 7 | 8 | number | 2 | 2 | \boxed{\frac{{15} + 5\sqrt{5}}{6} \cdot \sqrt[3]{{14} - 6\sqrt{5}}} | 3.6465 | 3.6465 | ['3.6295', '3.6465', '3.6465'] |
| 9 | 10 | number | 2 | 2 | \boxed{-9126} | -13689 | -13689 | ['-13689', '-13689', '-7203.3'] |
| 10 | 11 | number | 2 | 2 | \boxed{10} | 3 | 3 | ['\\infty', '3', '3'] |
| 13 | 14 | number | 2 | 2 | \boxed{59} | \text{No such primes exist} | \text{No such primes exist} | ['\\text{No such primes exist}', '\\text{No such primes exist}', '47'] |
| 17 | 18 | number | 2 | 3 | \boxed{\frac{\sqrt{3}}{45}} | \frac{2}{45} | \frac{2}{45} | ['\\frac{2}{45}', '\\frac{2}{45} \\cos\\frac{\\pi}{4050}', '\\frac{2}{45}'] |
| 18 | 19 | number | 2 | 2 | \boxed{666} | 703 | 703 | ['666', '703', '703'] |
| 20 | 21 | number | 3 | 3 | \boxed{230} | 104 | 104 | ['104', '104', '104'] |
| 21 | 22 | number | 2 | 2 | \boxed{\frac{208\cdot 3^{1/4}}{21}} | \sqrt{13} | \sqrt{13} | ['\\sqrt{13}', '\\sqrt{13}', '\\frac{343\\sqrt{3}}{9}'] |
| 22 | 23 | number | 2 | 2 | \boxed{-1} | 8 | 8 | ['8', '8', None] |
| 27 | 28 | number | 2 | 2 | \boxed{42} | 21 | 21 | ['21', '21', '0'] |
| 28 | 29 | number | 2 | 2 | \boxed{\frac{21}{103}} | \frac{1}{103} | \frac{1}{103} | ['\\frac{1}{103}', '\\frac{1}{103}', '\\frac{1}{5}'] |
| 30 | 31 | number | 3 | 3 | \boxed{2295} | 2175 | 2175 | ['2175', '2175', '2175'] |
| 32 | 33 | number | 3 | 3 | \boxed{34} | 51 | 51 | ['51', '51', '51'] |
| 35 | 36 | number | 2 | 2 | \boxed{343} | 181 | 181 | ['181', '181', '343'] |
| 42 | 43 | set | 2 | 2 | \boxed{\{40, 64, 75, 100, 150\}} | \{\} | \{\} | ['\\{\\}', '\\{\\}', '\\{40, 75, 150\\}'] |
| 43 | 44 | number | 3 | 3 | \boxed{8281323} | 209774391786 | 209774391786 | ['209774391786', '209774391786', '209774391786'] |
| 44 | 45 | number | 2 | 2 | \boxed{{2}^{2026}-1} | 2026 | 2026 | ['2026', '2026', '2025'] |
| 46 | 47 | number | 2 | 2 | \boxed{72} | 0 | 0 | ['0', '0', None] |
