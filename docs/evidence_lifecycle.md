# Evidence Lifecycle

Evidence is local-first. semscrape records extraction behavior into a local SQLite database, lets maintainers review and label records, exports privacy-controlled JSONL or ZIP bundles, audits bundles before sharing, and converts only trusted reviewed evidence into training data.

No evidence command automatically uploads data or trains a global model.

## Capture Local Evidence

Use `--record-evidence` on extraction or canary workflows:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --values-only

semscrape canary manifest.yml \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --out runs/canary.jsonl
```

Each field-level record stores command, policy, spec hash, input hash, field metadata, selected candidate id, status, value shape, validator details, ranker trace summary, failure reason, labels, and top-K candidate feature rows.

## Review And Label

Review locally before exporting or training:

```bash
semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
semscrape evidence review .semscrape/evidence.db --write-review-file runs/review.jsonl
```

Single records can be labeled directly:

```bash
semscrape evidence label .semscrape/evidence.db 123 --correct-candidate c0042
semscrape evidence label .semscrape/evidence.db 124 --correct-value "$59.99"
semscrape evidence label .semscrape/evidence.db 125 --abstention-correct
```

Editable review files can be applied back to the database:

```bash
semscrape evidence apply-review .semscrape/evidence.db runs/review-reviewed.jsonl
```

## Privacy Modes

| Mode | Intended use | Notes |
| --- | --- | --- |
| `full` | private local debugging only | Keeps raw candidate text, selectors, values, and full candidate rows. Do not share unless reviewed. |
| `redacted` | local/team review where hashes are useful | Hashes candidate text/context/descriptions/selected values, but is not as strict as `features-only`. |
| `features-only` | default contribution format | Designed to omit raw HTML, full candidate text, selectors, and raw values. |

For public-alpha contribution workflows, use `features-only` unless a maintainer explicitly asks for something else.

## Labels And Trust Levels

Label states separate observations from training truth:

- `unknown`: no trusted label exists yet.
- `labeled`: the record has a reviewed correction, expected value, correct candidate id, or correct abstention.

Trust levels are ordered:

```text
untrusted < bronze < silver < gold
```

Only `silver` and `gold` are trainable by default. Accepted production outputs are not automatically positive labels.

Allowed for training: benchmark/canary expected values, oracle-backed values, explicit user corrections, reviewed labels, and verified hard negatives.

Not allowed by default: unverified accepted outputs, ambiguous spec cases, holdout/adversarial rows, and normalization-only mismatches mislabeled as semantic negatives.

## Export JSONL

```bash
semscrape evidence export .semscrape/evidence.db \
  --privacy features-only \
  --min-trust silver \
  --out runs/evidence.jsonl
```

Useful flags:

- `--only-labeled`: export only labeled records.
- `--min-trust`: include records at or above a trust level.
- `--privacy`: choose `full`, `redacted`, or `features-only`.

## Bundle And Audit

Evidence bundles are ZIP files for opt-in sharing or maintainer intake:

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --min-trust silver \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
```

A bundle contains `manifest.json`, `records.jsonl`, `schema.json`, `privacy_report.json`, and `summary.json`.

The audit recomputes the privacy report and rejects schema/privacy mismatches. For normal features-only sharing, audit rejects raw HTML, full candidate text, selectors, and value text. Use `--allow-values` only for controlled private workflows where values have been reviewed and are allowed to be shared.

## Maintainer Intake

Maintainer-side intake validates and merges audited bundles:

```bash
semscrape evidence intake bundles/*.zip \
  --out data/intake/evidence.jsonl
```

Intake audits each bundle, rejects failed bundles, deduplicates records, writes merged JSONL, and preserves summaries for review and pack/ranker workflows. Intake does not train or promote a model by itself.

## Harvester And Review Queue

The automated alpha harvester records evidence locally per source, creates features-only bundles, audits them, merges intake, and writes review artifacts:

```bash
semscrape alpha run sources/external.yml \
  --policy ranker-local-safe \
  --privacy features-only \
  --out runs/auto/latest
```

Typical outputs include `summary.md`, `intake.jsonl`, `gaps.md`, `review-queue.jsonl`, per-source evidence bundles, and `harvest-manifest.json`.

Maintainers triage and convert review queue items explicitly:

```bash
semscrape review triage runs/auto/latest/review-queue.jsonl --out runs/review/triage.md
semscrape review export runs/auto/latest/review-queue.jsonl --limit 100 --priority high --out runs/review/batch.jsonl
semscrape review apply runs/review/batch-reviewed.jsonl \
  --intake runs/auto/latest/intake.jsonl \
  --out data/review/training-eligible-evidence.jsonl \
  --report runs/review/trust-conversion.json
```

False positives should become reviewed hard negatives. Candidate misses should become candidate-generation issues. Recoverable abstentions become positives only after explicit correction.

## Training Exports

Training datasets are built from trusted evidence exports or intake files with explicit commands:

```bash
semscrape dataset build \
  --from-evidence data/review/training-eligible-evidence.jsonl \
  --min-trust silver \
  --only-training-eligible \
  --training-split dev \
  --out data/candidate-ranking-from-evidence.jsonl
```

Pack builds can also consume trusted intake evidence:

```bash
semscrape pack build ecommerce \
  --from-intake data/intake/evidence.jsonl \
  --out packs/ecommerce-vNext \
  --min-trust silver \
  --only-training-eligible
```

Keep sealed holdout and adversarial splits out of training exports. Promotion still requires release checks against accumulated regression and adversarial suites.

## Safe Sharing Checklist

1. Use `features-only` unless there is a reviewed need for more detail.
2. Run `semscrape evidence audit bundle.zip`.
3. Confirm audit `ok` is true.
4. Confirm `privacy_report.json` does not contain raw HTML, full candidate text, selectors, or value text.
5. Share the bundle intentionally; no automatic upload happens.
