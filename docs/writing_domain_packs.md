# Writing Domain Packs

Domain packs are local configuration bundles for a specific extraction envelope. They collect policy defaults, thresholds, supported field notes, validator guidance, ranker artifacts, and release criteria without changing the core extractor.

The current pack shape is:

```text
packs/<name>/
  pack.yml
  validators.yml
  supported-fields.yml
  model-card.md
  ranker.json          # optional, unless pack.yml uses ranker: default
```

## What Goes In A Pack

Pack defaults should describe the safe operating envelope:

- `policy`: usually `ranker-local-safe` for public-alpha/high-precision workflows.
- `ranker`: `default` or a pack-local `ranker.json`.
- `thresholds`: confidence, margin, validator, ranker, penalty, and fallback settings.
- `validators`: field-level validator notes or defaults.
- `supported_fields`: the field kinds and names the pack is intended to handle.
- `model_card`: training data, evaluation runs, known traps, and promotion limits.
- `metadata`: build source, dataset counts, release-check summary, and frozen-run details.

Do not put these in a pack:

- unverified production positives
- raw private evidence
- raw HTML copied from users
- broad rules that hide false positives instead of making them visible
- thresholds that improve coverage by weakening safety without a release-check result

## Build Workflow

Use local evidence first, and keep training boundaries explicit.

1. Collect local evidence.

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --pack ecommerce \
  --record-evidence \
  --evidence-db .semscrape/evidence.db
```

2. Review and label records.

```bash
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
semscrape evidence label .semscrape/evidence.db RECORD_ID --correct-candidate CANDIDATE_ID
```

3. Export privacy-safe evidence or intake bundles.

```bash
semscrape evidence export .semscrape/evidence.db \
  --only-labeled \
  --privacy features-only \
  --out runs/evidence/features-only.jsonl
```

4. Build a candidate-ranking dataset from trusted evidence.

```bash
semscrape dataset build \
  --from-evidence runs/evidence/features-only.jsonl \
  --only-training-eligible \
  --training-split train_candidate \
  --out runs/pack/candidate-ranking.jsonl
```

5. Train or build a pack from trusted intake evidence.

```bash
semscrape pack build ecommerce \
  --from-intake runs/evidence/features-only.jsonl \
  --out packs/ecommerce-candidate \
  --only-training-eligible \
  --training-split train_candidate
```

6. Run release checks before promoting.

```bash
semscrape pack release-check packs/ecommerce-candidate \
  --baseline packs/ecommerce \
  --holdout corpus/base_holdout/manifest.yml \
  --adversarial corpus/adversarial_holdout/manifest.yml \
  --out runs/pack/ecommerce-candidate-release-check.json
```

## Validation Standard

Evaluate pack changes against separate corpora:

- `train/dev`: used to build rules or rankers.
- `regression`: known incidents that must not regress.
- `sealed holdout`: not inspected during development.
- `adversarial holdout`: traps that should preserve false-positive safety.
- `true external cohort`: outside projects frozen before the run.

Promotion should require:

- no false-positive regression
- no adversarial false positives
- no training from untrusted production positives
- no raw private evidence in features-only exports
- no material candidate-recall regression
- coverage improvements only after false-positive safety is preserved

## Documentation Checklist

Each pack release should document:

- supported field envelope
- known traps and abstention behavior
- ranker artifact and feature schema
- training source and trust levels
- excluded data and privacy mode
- release-check command and result
- promotion decision

Existing examples:

- `packs/ecommerce/pack.yml`
- `packs/ecommerce-v1/model-card.md`
- `docs/domain_packs/ecommerce.md`
