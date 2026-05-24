# M17S Harvester Scale Report

Status: passed.

Tested target:

```text
tag: v0.1.0-alpha.10
commit: b4a5020
```

Run:

```bash
semscrape alpha run runs/m17s/source-registry.yml \
  --policy ranker-local-safe \
  --record-evidence \
  --privacy features-only \
  --out runs/auto/m17s \
  --force \
  --no-respect-rate-limits \
  --pack ecommerce
```

The source registry was generated from public-page replay snapshots already present in the local pilot corpus. This avoids live-site load and makes the scale result reproducible.

Aggregate result:

```text
sources:                  102
bundles:                  102
domains/source groups:    25
fields_attempted:         464
coverage_rate:            0.678879
false_positive_rate:      0.002155
candidate_recall@40:      0.995633
abstention_rate:          0.321121
bundle_audit_pass_rate:   1.000000
review_queue_items:       296
hard_negatives_created:   5278
```

Split result:

```text
dev:
  rows:                   353
  coverage_rate:          0.699717
  false_positive_rate:    0.002833
  candidate_recall@40:    0.997167

holdout:
  rows:                   105
  coverage_rate:          0.647619
  false_positive_rate:    0.000000
  candidate_recall@40:    0.990476

adversarial:
  rows:                   6
  coverage_rate:          0.000000
  false_positive_rate:    0.000000
  note:                   all adversarial rows abstained
```

Review queue:

```text
false positives:          1
candidate misses:         2
eligible for training:    0
```

The one false positive was in the dev split:

```text
source: founder_external_listing_hockey_forms_002
field:  first_win_pct
expected: 0.55
actual:   0.425
```

Safety and trust:

```text
features-only bundle audit passed for every bundle.
No training dataset was produced.
No ranker or pack was promoted.
No review-queue item was marked eligible for global training.
Holdout and adversarial splits remained measurement-only.
```

Decision:

```text
M17S passed.
Next milestone should use trusted reviewed evidence only, not raw accepted outputs.
```

