# SlopGuard scorer evaluation

## Methodology

This evaluates the deterministic scorer against a small author-labelled corpus. Registry results are fetched read-only and cached by core. `UNKNOWN` registry outcomes are excluded; an alleged phantom that exists is a label conflict and is excluded.

## Operating point: verdict ≥ REVIEW

| TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 2 | 43 | 0 | 92.6% | 100.0% | 96.2% | 97.1% |

Confusion matrix: actual risky → flagged/not flagged = 25/0; actual safe → flagged/not flagged = 2/43

## Operating point: verdict ≥ RISKY

| TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 25 | 2 | 43 | 0 | 92.6% | 100.0% | 96.2% | 97.1% |

Confusion matrix: actual risky → flagged/not flagged = 25/0; actual safe → flagged/not flagged = 2/43

## Per-category breakdown

| Category | Included | Review F1 | Risky F1 |
| --- | ---: | ---: | ---: |
| risky-lookalike | 10 | 100.0% | 100.0% |
| risky-phantom | 15 | 100.0% | 100.0% |
| safe-niche | 15 | 0.0% | 0.0% |
| safe-popular | 30 | 0.0% | 0.0% |

## Errors

### Verdict ≥ REVIEW

- **false positive** `axios` (safe-popular; BLOCK): malicious_advisory: A public advisory identifies this package as malicious.
- **false positive** `chalk` (safe-popular; BLOCK): malicious_advisory: A public advisory identifies this package as malicious.

### Verdict ≥ RISKY

- **false positive** `axios` (safe-popular; BLOCK): malicious_advisory: A public advisory identifies this package as malicious.
- **false positive** `chalk` (safe-popular; BLOCK): malicious_advisory: A public advisory identifies this package as malicious.

## Exclusions and label conflicts

Unknown registry outcomes excluded: 0.
Phantom label conflicts excluded: 0.

## Limitations

This is a small author-labelled set, not an independent ground truth. Popularity-based signals can penalise legitimate new or small packages. The npm top list is curated rather than a comprehensive popularity source. This is not a malware detector.
