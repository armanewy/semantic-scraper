# Evidence Workflow

Evidence capture is local and opt-in. It is designed to support review, privacy-safe sharing, and trusted label generation without turning raw accepted outputs into global training positives.

## Capture local evidence

```bash
semscrape canary corpus/ood_holdout/manifest.yml \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --out runs/ood-holdout.jsonl
```

You can also record evidence from `extract`:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --values-only
```

## Review records

```bash
semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
```

When a field abstains, inspect candidates before loosening gates:

```bash
semscrape inspect spec.yml inputs/example.html FIELD_NAME
```

If the correct value is missing from the top candidates, the next fix is candidate generation or spec clarity, not ranker-threshold loosening.

## Label trusted corrections

```bash
semscrape evidence label .semscrape/evidence.db 123 --correct-candidate c0017
semscrape evidence label .semscrape/evidence.db 124 --correct-value "$59.99"
semscrape evidence label .semscrape/evidence.db 125 --abstention-correct
```

Global-training exports should use trusted labels only:

```text
gold       explicit corrections, manually reviewed labels, benchmark/canary expected values
silver     confirmed fallback or repeated validated canary evidence
bronze     high-confidence production evidence without ground truth
untrusted  unknown production outputs
```

## Export and audit privacy-safe bundles

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --min-trust silver \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
```

Privacy modes:

```text
full          keeps candidate values/text/context for local debugging
redacted      keeps candidate values and ML features, replaces long text/context with hashes
features-only keeps labels and ML features, omits raw values/text/context/selectors
```

Features-only bundles include `manifest.json`, `records.jsonl`, `schema.json`, `privacy_report.json`, and `summary.json`. The privacy audit rejects bundles that contain raw HTML, selectors, full candidate text, or raw values unless values are explicitly allowed.

## Maintainer intake and review queues

```bash
semscrape evidence intake bundles/*.zip \
  --out data/intake/evidence.jsonl

semscrape review triage runs/auto/latest/review-queue.jsonl \
  --out runs/review/triage.md

semscrape review export runs/auto/latest/review-queue.jsonl \
  --limit 100 \
  --priority high \
  --out runs/review/batch.jsonl

semscrape review apply runs/review/batch-reviewed.jsonl \
  --intake runs/auto/latest/intake.jsonl \
  --out data/review/training-eligible-evidence.jsonl \
  --report runs/review/trust-conversion.json
```

Maintainer-side intake validates privacy, schema version, and duplicate records before writing merged evidence. Harvester and review flows do not train or promote rankers/packs by themselves.

## Training boundary

Allowed for global training:

- benchmark/canary expected values
- explicit user corrections
- manually reviewed labels
- verified hard negatives
- oracle-backed expected values

Not allowed by default:

- accepted production outputs without ground truth
- ambiguous spec cases
- normalization-only mismatches mislabeled as semantic negatives
- holdout, adversarial, or monitor-only rows
