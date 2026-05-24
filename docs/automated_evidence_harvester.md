# Automated External Evidence Harvester

M17 adds a local, opt-in harvester for continuously collecting privacy-safe extraction evidence from fresh sources.

The safety boundary is strict:

```text
Automatically collect evidence: yes
Automatically label raw outputs as positives: no
Automatically promote rankers or packs: no
```

## Run

```bash
semscrape alpha run sources/external.yml \
  --policy ranker-local-safe \
  --privacy features-only \
  --out runs/auto/latest
```

Optional scheduled local run:

```powershell
.\scripts\run_alpha_harvester.ps1 -Registry sources/external.yml -OutRoot runs/auto -Pack ecommerce
```

## Registry

Each source declares its split, expected-value mode, label policy, and privacy mode:

```yaml
schema_version: 1
sources:
  - id: pypi_bs4_project
    domain: package
    spec: sources/specs/pypi_project.yml
    input: snapshots/pypi_bs4.html
    split: train_candidate
    expected_mode: manual
    label_policy: review_required
    privacy: features-only
    rate_limit_seconds: 10
```

Supported splits:

```text
dev
holdout
adversarial
monitor_only
train_candidate
```

Supported label policies:

```text
review_required
benchmark
oracle
monitor_only
none
```

## Outputs

The run directory contains:

```text
summary.md
gaps.md
intake.jsonl
review-queue.jsonl
harvest-manifest.json
evidence-bundles/
sources/
snapshots/
```

`review-queue.jsonl` prioritizes:

```text
false_positive
candidate_recall_miss
recoverable_abstention
low_margin_accept
risky_region_accept
unverified_extraction
```

## Review Conversion

Maintainers can triage the queue without treating raw outputs as labels:

```bash
semscrape review triage runs/auto/latest/review-queue.jsonl \
  --out runs/review/review-triage.md

semscrape review export runs/auto/latest/review-queue.jsonl \
  --limit 100 \
  --priority high \
  --out runs/review/review-batch.jsonl
```

After editing the batch file with explicit review decisions, apply it to the intake JSONL:

```bash
semscrape review apply runs/review/review-batch-reviewed.jsonl \
  --intake runs/auto/latest/intake.jsonl \
  --out data/review/training-eligible-evidence.jsonl \
  --report runs/review/trust-conversion.json
```

Only reviewed gold/silver rows from non-holdout, non-adversarial splits can be exported by this workflow. Recoverable abstentions and unverified extractions remain non-training telemetry until a reviewer explicitly labels them.

## Oracle Labels

M18B adds oracle-backed expected values. Oracle rows are trusted expected values from a separate source, not semscrape's own extracted output:

```yaml
sources:
  - id: pypi_bs4_project
    domain: package_registry
    spec: sources/specs/pypi_project.yml
    input: snapshots/pypi_bs4.html
    split: train_candidate
    expected_mode: oracle
    label_policy: oracle
    oracle:
      type: pypi_json
      package: beautifulsoup4
      fields:
        package_name: info.name
        version: info.version
        summary: info.summary
```

Supported oracle types:

```text
manual_expected
pypi_json
npm_registry
github_repo
json_ld
```

Resolve and inspect label yield:

```bash
semscrape oracle resolve sources/external.yml \
  --out runs/oracle/oracle-expected.jsonl

semscrape oracle report runs/oracle/oracle-expected.jsonl \
  --out runs/oracle/oracle-label-yield.md
```

Feed oracle values into the harvester:

```bash
semscrape alpha run sources/external.yml \
  --resolve-oracles \
  --policy ranker-local-safe \
  --privacy features-only \
  --out runs/auto/latest
```

When `--resolve-oracles` is used, `alpha run` also writes `oracle-expected.jsonl`, `oracle-label-yield.md`, and `oracle-training-eligible-evidence.jsonl`. The training-eligible oracle export is still only evidence JSONL; it does not build a candidate-ranking dataset and does not promote a model.

## Training Rules

Raw extraction outputs are telemetry. They are not positive training labels.

Global ranker/domain-pack training may use:

```text
gold labels
selected silver labels
```

It must not use:

```text
bronze positives by default
untrusted positives
holdout/adversarial rows as training data
```

`alpha run` intentionally does not create a training dataset and does not promote a model. Any ranker or pack update still requires an explicit build and release-check.
