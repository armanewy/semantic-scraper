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
