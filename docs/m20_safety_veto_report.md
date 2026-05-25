# M20 Safety Veto and Positive Label Expansion Report

Status: completed, opt-in veto policy added.

Question: Can the oracle-trained safety signal block known traps while preserving baseline coverage, and can the coverage-regression positives be captured for future training/evaluation?

## Implementation

M20 adds an internal blocking-only policy:

```text
ranker-local-safe-veto
```

Runtime behavior:

```text
ranker-local-safe accepts a candidate
  -> safety veto ranker scores that accepted candidate
  -> if positive confidence is below the veto threshold, abstain
  -> otherwise keep the baseline accepted candidate
```

The veto cannot recover candidates that the baseline rejected. It only blocks accepted values.

Commands added:

```text
semscrape ranker veto-eval DATASET.jsonl \
  --model models/candidate-ranker-v3.json \
  --veto-ranker models/candidate-ranker-vNext.json \
  --veto-confidence-below 0.60 \
  --out runs/m20/oracle-eval-veto.jsonl
```

Extraction/canary commands now accept:

```text
--policy ranker-local-safe-veto
--veto-ranker models/candidate-ranker-vNext.json
--veto-confidence-below 0.60
```

`ranker-local-safe` remains the default public-alpha policy.

## Veto Evaluation

Oracle eval:

| mode | coverage | FPR | recall@40 |
|---|---:|---:|---:|
| v3 baseline | 0.645161 | 0.064516 | 1.000000 |
| veto mode | 0.548387 | 0.000000 | 1.000000 |

Oracle diff:

```text
false_positive_fixed: 2
coverage_lost_correct: 1
same_correct: 17
same_abstained: 11
```

The veto caught the two oracle-eval false positives that motivated the experiment. It also vetoed one known-correct oracle row, so it is still conservative.

Base holdout:

| mode | coverage | FPR | recall@40 |
|---|---:|---:|---:|
| v3 baseline | 0.450000 | 0.000000 | 1.000000 |
| veto mode | 0.450000 | 0.000000 | 1.000000 |

Base diff:

```text
same_correct: 9
same_abstained: 11
coverage_lost_correct: 0
```

Adversarial holdout:

```text
false_positive_rate: 0.000000
coverage_rate:       0.000000
```

M20 release-check with a coverage-loss bound of 5% relative to v3 passed:

```text
min_coverage:             0.427500
base_coverage:            0.450000
candidate_coverage:       0.450000
base_fpr:                 0.000000
candidate_fpr:            0.000000
adversarial_fpr:          0.000000
coverage_not_regressed:   true
fpr_not_regressed:        true
```

## Must-Keep Positives

M20 records the six known-correct base-holdout rows that vNext lost:

```text
data/regression/must_keep_positives.jsonl
```

Rows:

```text
docs/install_command
docs/page_title
ecommerce/availability
ecommerce/price
ecommerce/rating
recipes/servings
```

Usage:

```text
regression_only_not_training
```

These are gold must-keep positives for future evaluation. They should not be silently folded into normal training because they came from a sealed base holdout. A future training milestone can intentionally move equivalent non-holdout examples into training.

Veto result on must-keep rows:

```text
must_keep_positive_veto_rate: 0.000000
```

## Decision

`ranker-local-safe-veto` is available as an internal opt-in evaluation policy.

No default is changed:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

Reason:

```text
The veto passed the narrow M20 gate and is useful for evaluation, but it still needs broader external/regression coverage before becoming a public default.
```

## Next Need

The next label milestone should expand non-holdout trusted positives around the must-keep families:

```text
docs main titles and install commands
ecommerce price/rating/availability
recipe servings and metadata
pricing/table cells
listing/card titles
```

Target:

```text
250+ trusted labels
100+ gold positives
100+ hard negatives
50+ must-keep-style positives from non-holdout sources
```
