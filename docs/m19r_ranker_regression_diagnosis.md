# M19R Ranker Regression Diagnosis

Status: completed, no promotion.

Question: Can the oracle-trained safety signal be used without collapsing coverage on existing holdouts?

## Tools Added

M19R added two diagnostic commands:

```text
semscrape ranker diff LEFT.jsonl RIGHT.jsonl --left-label v3 --right-label vNext --out DIFF.jsonl --summary-out DIFF.md
semscrape dataset balance DATASET.jsonl --out BALANCED.jsonl --max-hard-negatives-per-positive 3 --max-negatives-per-positive 4
```

`ranker diff` compares per-field eval rows and classifies transitions such as `false_positive_fixed`, `coverage_lost_correct`, and `coverage_gained_correct`.

`dataset balance` caps hard-negative and plain-negative rows per positive example and sets explicit sample weights. It is a training recipe tool only; it does not promote a ranker.

## Baseline vs vNext Diagnosis

Oracle eval split:

```text
rows: 31
false_positive_fixed: 2
coverage_lost_correct: 1
same_correct: 17
same_abstained: 11
```

The two false positives fixed by vNext were both `first_content_link` rows in docs/database-style pages. v3 accepted plausible but wrong content links; vNext abstained with `low_ranker_confidence`.

Base holdout:

```text
rows: 20
coverage_lost_correct: 6
same_correct: 3
same_abstained: 11
```

Coverage loss was spread across:

```text
ecommerce: price, rating, availability
docs: page_title, install_command
recipes: servings
```

All major lost rows were correct v3 extractions that vNext changed into `low_ranker_confidence` abstentions. That means the candidate recall path is healthy, but vNext learned an overly conservative acceptance boundary.

## Balanced Training Recipe

M19R tested a balanced oracle train split:

```text
source: data/m19/candidate-ranking-oracle-train.jsonl
balanced_train_rows: 799
positives: 131
hard_negatives: 254
caps:
  hard_negatives_per_positive: 3
  plain_negatives_per_positive: 4
weights:
  positive: 10
  hard_negative: 2
  negative: 1
```

Balanced candidate eval:

| suite | coverage | FPR | recall@40 |
|---|---:|---:|---:|
| oracle eval | 0.548387 | 0.000000 | 1.000000 |
| base holdout | 0.550000 | 0.000000 | 1.000000 |
| adversarial holdout | 0.000000 | 0.000000 | 0.000000 |

Base holdout diff versus v3:

```text
coverage_gained_correct: 4
coverage_lost_correct: 2
same_correct: 7
same_abstained: 7
```

The balanced recipe is materially better than the original vNext replacement on base coverage, but it still does not clear the existing release gate:

```text
release-check passed: false
failed gate: base_coverage
promotion: keep_baseline
```

## Safety Veto Assessment

vNext is not promoted as a safety veto in M19R.

Reason:

```text
The useful oracle false-positive fixes and the harmful base/ecommerce coverage losses are both expressed mostly as low-confidence abstentions.
```

A simple rule like "let vNext veto v3 when vNext abstains" would preserve the oracle FPR fixes but also suppress many known-correct base/ecommerce rows. A narrower confidence-band veto would be brittle and not release-worthy without more labeled validation.

## Decision

No ranker, pack, or veto policy is promoted.

Current defaults remain:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

M19R did identify a better next training recipe:

```text
balanced positive/hard-negative mix
field/domain-specific evaluation before promotion
more trusted positive labels from ecommerce, listings, pricing, docs, and package pages
```

## Next Need

The bottleneck is not tooling or candidate recall. It is trusted label distribution.

Before another promotion attempt, collect broader oracle/reviewed labels:

```text
more ecommerce/listings/pricing positives
more base-holdout-like positive families
more reviewed hard negatives tied to repeated traps
separate oracle holdout labels for evaluation
```

Suggested next evidence milestone:

```text
M18C: Broader Oracle Coverage and Holdout Labels
```
