# Known Limitations

`v0.1.0-alpha.4` is a controlled public alpha. It is safe enough for limited external use, but it is not a universal scraper.

## Scope

Supported best today:

- static or replayed HTML
- rendered snapshots captured with Playwright
- product, article, docs/reference, listings, pricing/table, and similar page families
- workflows where abstention is acceptable and can be reviewed

Not included:

- anti-bot bypassing
- CAPTCHA solving
- proxy rotation
- login/session workflow automation
- large-scale crawling or scheduling
- hosted dashboards
- automatic cloud upload
- automatic global model training from user runs

## Safety Model

The public-alpha default is `ranker-local-safe`. It intentionally trades some coverage for fewer false positives.

Expected behavior:

- strong evidence: extract
- ambiguous evidence: abstain
- missing candidates: abstain
- unsafe region/trap: abstain

A missing field is a workflow/product issue. A silent wrong value is a correctness issue.

## Generalization

The current validation result covers the checked-in holdouts, accumulated external-style regressions, and the M15R mini-holdout. It does not prove arbitrary web robustness.

Users should run canaries for their own page families:

```bash
semscrape canary manifest.yml --record-evidence --out runs/canary.jsonl
```

## Evidence Privacy

Features-only evidence bundles are the default contribution format. They are intended to omit raw HTML, full candidate text, selectors, and raw values.

Always audit before sharing:

```bash
semscrape evidence audit semscrape-evidence-bundle.zip
```

Do not share full/redacted bundles publicly unless you have reviewed their contents and have the right to share them.

## Training Discipline

The base ranker must not train on unverified production positives by default.

Allowed for global training:

- benchmark/canary expected values
- explicit user corrections
- manually reviewed labels
- verified hard negatives

Not allowed by default:

- accepted production outputs without ground truth
- ambiguous spec cases
- normalization-only mismatches mislabeled as semantic negatives
