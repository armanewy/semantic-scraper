# M18 Review Queue Conversion Report

Status: passed.

Input artifacts:

```text
review queue: runs/auto/m17s/review-queue.jsonl
intake:       runs/auto/m17s/intake.jsonl
```

Commands:

```bash
semscrape review triage runs/auto/m17s/review-queue.jsonl \
  --out runs/m18/review-triage.md

semscrape review export runs/auto/m17s/review-queue.jsonl \
  --limit 100 \
  --priority high \
  --out runs/m18/review-batch.jsonl

semscrape review apply runs/m18/review-batch-reviewed.jsonl \
  --intake runs/auto/m17s/intake.jsonl \
  --out data/m18/training-eligible-evidence.jsonl \
  --report runs/m18/trust-conversion.json
```

Review queue triage:

```text
total review items:       296
high priority items:      144
training eligible before review: 0

false positives:          1
candidate recall misses:  2
recoverable abstentions:  141
low-margin accepts:       146
plain abstentions:        6
```

Batch conversion:

```text
reviewed batch size:      100
reviewed items:           100
gold hard negatives:      1
candidate-generation issues: 2
deferred manual reviews:  97
training eligible rows:   1
training excluded rows:   99
privacy passed:           true
```

The reviewed gold hard negative is the M17S dev-split false positive:

```text
source:   founder_external_listing_hockey_forms_002
field:    first_win_pct
expected: 0.55
actual:   0.425
action:   reviewed gold hard negative / table-row disambiguation evidence
```

The two candidate misses were classified as candidate-generation issues:

```text
source: founder_external_docs_iana_example_domains_001
field:  organization_name
action: candidate-generation backlog/test

source: m16r_holdout_holdout_docs_python_controlflow_001
field:  tutorial_home
action: holdout candidate-generation backlog/test, not training data
```

Trust boundary:

```text
No unverified accepted extraction was converted into a positive training label.
Holdout/adversarial rows remain excluded from training exports.
Recoverable abstentions remain deferred until explicit value review.
The training export contains one reviewed dev-split hard-negative evidence row.
```

Decision:

```text
Do not train a new ranker/pack from M18 alone. One reviewed hard-negative row is useful regression/training material, but not enough for a model update.
Next data-moat step should acquire more trusted labels, preferably through oracle-backed sources and/or explicit human review batches.
```

