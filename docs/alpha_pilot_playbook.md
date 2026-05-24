# semscrape Alpha Pilot Playbook

This playbook is for external alpha users running semscrape on their own local pages or replay snapshots.

The goal is not to force extraction at all costs. semscrape should extract when evidence is strong and abstain when a value is unsafe or ambiguous. A missing value is a workflow issue; a silent wrong value is a correctness issue.

## 1. Create A Project

```bash
semscrape init my-project
cd my-project
```

Edit `spec.yml` so each field describes intent, not CSS structure:

```yaml
fields:
  - name: price
    type: price
    description: Current purchase price, not list price, shipping, coupon savings, or installment amount.
    hints: [current price, sale price, buy box]
```

## 2. Inspect Candidates

Use inspect before changing thresholds:

```bash
semscrape inspect spec.yml inputs/example.html price
```

If the correct value is absent from the top candidates, improve candidate generation, rendered snapshots, or the spec. A ranker cannot recover a candidate it never sees.

## 3. Extract Safely

Run the offline ranker path first:

```bash
semscrape extract spec.yml inputs/example.html \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db
```

For scripts, require important fields:

```bash
semscrape extract spec.yml inputs/example.html \
  --policy ranker-local-safe \
  --require-fields title price availability \
  --fail-on-abstain \
  --min-coverage 0.75
```

## 4. Run A Canary

Add replay cases to `manifest.yml`, then run:

```bash
semscrape canary manifest.yml \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --out runs/canary.jsonl
```

Use replay HTML whenever possible so failures are reproducible.

## 5. Review And Correct

Review abstentions and failures:

```bash
semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
```

Write a batch review file:

```bash
semscrape evidence review .semscrape/evidence.db \
  --status abstained \
  --limit 20 \
  --write-review-file review.jsonl
```

Edit `review.jsonl`, then apply:

```bash
semscrape evidence apply-review .semscrape/evidence.db review.jsonl
```

User corrections become gold labels. Do not train from unverified production guesses.

## 6. Bundle Evidence

Create a privacy-safe contribution bundle:

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --min-trust silver \
  --out semscrape-evidence-bundle.zip
```

Audit before sharing:

```bash
semscrape evidence audit semscrape-evidence-bundle.zip
```

The default features-only mode omits raw HTML, full candidate text, selectors, and raw values.

## 7. Pilot Reports

For a structured pilot project:

```bash
semscrape pilot run pilots/ecommerce_alpha_001 --pack ecommerce
semscrape pilot report pilots/ecommerce_alpha_001 --out pilots/ecommerce_alpha_001/pilot-report.md
```

Summarize multiple pilots:

```bash
semscrape pilot summarize pilots/* --out runs/m13/alpha-pilot-summary.md
```

## 8. Pack Gap Analysis

After intake:

```bash
semscrape evidence intake bundles/*.zip --out data/intake/evidence.jsonl
semscrape pack gaps data/intake/evidence.jsonl --pack ecommerce --out runs/m13/ecommerce-gaps.md
```

Use gaps to decide whether to improve candidate generation, validators, field specs, safety gates, or a domain pack.

## Alpha Success Criteria

- Features-only bundles pass privacy audit.
- Aggregate false-positive rate stays at or below 2%.
- Manual trap cases have zero false positives.
- Ranker-local aggregate coverage is at least 60%.
- Every false positive becomes a gold hard-negative label before training.
- Pack/ranker candidates must pass release-check before promotion.
