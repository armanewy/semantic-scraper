# M19 Evidence-Driven Ranker/Pack Update Report

Status: completed, no promotion.

Question: Can oracle-backed trusted labels improve the default ranker or a domain pack without regressing false-positive safety?

## Dataset

Input:

```text
data/m18b/oracle-training-eligible-evidence.jsonl
```

Build command:

```text
semscrape dataset build --from-evidence data/m18b/oracle-training-eligible-evidence.jsonl --include-hard-negatives --only-training-eligible --training-split train_candidate --out data/m19/candidate-ranking-oracle.jsonl
```

Result:

```text
candidate_rows:       3920
positive_rows:        186
hard_negative_rows:   1498
groups:               25
training_splits:      train_candidate only
min_trust:            silver
only_training_eligible: true
```

Group-aware split:

```text
train_rows:           2680
train_positives:      131
train_hard_negatives: 1091
train_groups:         16

eval_rows:            1240
eval_positives:       55
eval_hard_negatives:  407
eval_groups:          9
```

Privacy check:

```text
No raw candidate_value, candidate_text, or expected value fields are present in the M19 dataset JSONL.
```

## Ranker Candidate

Candidate:

```text
models/candidate-ranker-vNext.json
models/candidate-ranker-vNext.md
```

Training metadata:

```text
rows:            2680
positives:       131
negatives:       2549
hard_negatives:  1091
features:        41
threshold:       0.70
margin:          0.00
```

Oracle eval split:

| model | coverage | FPR | recall@40 |
|---|---:|---:|---:|
| candidate-ranker-v3 | 0.645161 | 0.064516 | 1.000000 |
| candidate-ranker-vNext | 0.548387 | 0.000000 | 1.000000 |

Interpretation:

```text
vNext eliminated the oracle eval false positives but lost coverage.
```

Release-check against sealed replay suites:

| suite | baseline coverage | candidate coverage | baseline FPR | candidate FPR |
|---|---:|---:|---:|---:|
| base_holdout | 0.450000 | 0.150000 | 0.000000 | 0.000000 |
| adversarial_holdout | n/a | 0.000000 | n/a | 0.000000 |

Result:

```text
ranker release-check passed: false
promotion: keep_baseline
failed gates: base_coverage, coverage_not_regressed
```

## Pack Candidate

Candidate:

```text
packs/ecommerce-vNext
```

Build input:

```text
data/m18b/oracle-training-eligible-evidence.jsonl
```

Release-check:

| pack | coverage | FPR | recall@40 |
|---|---:|---:|---:|
| ecommerce-v1 baseline | 0.800000 | 0.000000 | 1.000000 |
| ecommerce-vNext candidate | 0.150000 | 0.000000 | 1.000000 |
| adversarial candidate | 0.000000 | 0.000000 | 0.000000 |

Result:

```text
pack release-check passed: false
promotion: keep_baseline
failed gates: coverage_floor, coverage_not_regressed
```

## Decision

M19 passed as a controlled update attempt, but no ranker or pack is promoted.

The oracle-backed labels are useful: they produced many hard-negative rows and showed a real safety gain on the oracle eval split. The label/domain mix is still too narrow, however. The candidate models become over-conservative and fail the coverage gates on sealed base holdout and ecommerce pack release-checks.

Current packaged defaults remain:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe public-alpha policy
```

## Next Need

The next evidence milestone should expand trusted label coverage before another promotion attempt:

```text
- more oracle-backed domains, especially ecommerce/listings/pricing
- more positive labels for current base-holdout field families
- more reviewed hard negatives from risky accepts and false positives
- holdout oracle labels reserved for evaluation rather than training
```

Suggested next milestone:

```text
M18C: Broader Oracle Coverage and Holdout Labels
```

