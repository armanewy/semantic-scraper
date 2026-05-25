# semscrape

semscrape is a local-first semantic scraper CLI that extracts named fields from HTML with deterministic ranking, validators, selector memory, and optional local Ollama fallback.

## What this is good for

- Local/offline extraction from static HTML, replayed HTML, and optional Playwright-rendered snapshots.
- Product, article, docs/reference, listing, pricing/table, and similar page families where fields can be described clearly.
- Workflows where correctness matters more than coverage, and an abstention can be reviewed.
- Building small local extraction specs, running canaries, recording evidence, and improving ranker/packs from trusted labels.
- Developer alpha usage where privacy-safe evidence bundles can be audited before sharing.

## What this is not for

- CAPTCHA solving, anti-bot bypassing, proxy rotation, or login/session automation.
- Large-scale crawling, scheduling, hosted dashboards, billing, or team workflow management.
- Automatic cloud upload or automatic global model training from unverified user runs.
- "Always return something" scraping. The default posture should prefer abstention over false positives.

## Quickstart from fresh clone

```bash
git clone https://github.com/armanewy/semantic-scraper.git
cd semantic-scraper

python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
. .\.venv\Scripts\Activate.ps1

python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q

semscrape doctor
semscrape ranker info
semscrape extract examples/product.yml examples/product_v2.html --values-only
```

For rendered pages, install the optional render extra and Chromium:

```bash
python -m pip install -e ".[render]"
playwright install chromium
```

## Minimal spec example

```yaml
name: product_card
fields:
  - name: price
    type: price
    description: Current sale price, not the old/list/strikethrough price.
    hints: [current price, sale price, now, deal, offer]
    validators:
      require_currency: true
      regex_not: ["999\\.99"]

benchmarks:
  product_v2.html:
    price: "$59.99"
```

Supported field types:

```text
text, price, number, date, url, email, bool
```

## Example extract command

Run the packaged offline ranker with the public-alpha-safe policy:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --policy ranker-local-safe \
  --values-only
```

Expected output:

```json
{
  "title": "AeroPress Go Travel Coffee Press",
  "price": "$59.99",
  "rating": "4.7",
  "availability": "Available now"
}
```

Use required-field gates in scripts:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --require-fields title price availability \
  --fail-on-abstain \
  --min-coverage 0.75 \
  --values-only
```

Exit codes for alpha scripting:

```text
0 = extraction/check succeeded
1 = extraction completed, but required fields or minimum coverage failed
2 = config/spec/runtime error
3 = reserved for render/network errors
4 = model or ranker unavailable
```

## Example abstention/safety behavior

Abstention is intentional. If the correct value is missing or ambiguous, semscrape should return `null` and a nonzero script exit when the field is required, instead of guessing.

```bash
semscrape extract fixtures/listings/search_results/spec.yml \
  fixtures/listings/search_results/v4_missing_field.html \
  --policy ranker-local-safe \
  --require-fields coupon_code \
  --fail-on-abstain \
  --values-only
```

That fixture has no active coupon. The safe outcome is `coupon_code: null`; a silent invented coupon would be a correctness bug.

When a field abstains, inspect candidates before changing thresholds:

```bash
semscrape inspect fixtures/listings/search_results/spec.yml \
  fixtures/listings/search_results/v4_missing_field.html \
  coupon_code
```

If the correct candidate is not present, the next fix is candidate generation or spec clarity, not looser acceptance gates.

## Policies overview

`conservative` is deterministic and LLM-free. It uses strict heuristic gates and is useful for baseline canary/replay checks.

`ranker-local` uses the packaged offline candidate ranker without Ollama or an explicit `--ranker` path. It is useful when local coverage matters and you still want deterministic behavior.

`ranker-local-safe` is the public-alpha default. It uses no LLM calls, tightens ranker confidence, margin, validator-confidence, penalty, visibility, and field-aware safety gates, and prefers abstention over false positives.

`ranker-plus-llm` runs the local ranker first, then calls a local Ollama model only after recoverable abstentions. Model choices still have to pass validation and strict gates.

Internal veto policies also exist for evaluation, but they are not the recommended public default. See [Policies](docs/policies.md) for the full policy notes.

## Evidence/privacy summary

Evidence capture is opt-in and local by default:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --values-only

semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
```

Privacy-safe contribution bundles should use `features-only` and should be audited before sharing:

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
```

Features-only bundles are intended to omit raw HTML, selectors, full candidate text, and raw values. Global training should use trusted labels only, such as expected values, explicit corrections, reviewed labels, or verified hard negatives.

## Current release status

- Package version in `pyproject.toml`: `0.1.0`.
- Project status: controlled public alpha, not a universal scraper.
- Default/recommended alpha posture: `ranker-local-safe`, local/offline first, abstention before false positives.
- Current default artifacts remain `candidate-ranker-v3` and `packs/ecommerce-v1` in the milestone record.
- M16C true outside-user validation is still pending; later evidence/ranker/veto work through M22E did not promote a new public default.

Detailed milestone and evaluation history lives outside the README now.

## Deeper docs

- [Architecture](docs/architecture.md)
- [Policies](docs/policies.md)
- [Reason codes](docs/reason_codes.md)
- [Evidence lifecycle](docs/evidence_lifecycle.md)
- [Known limitations](docs/known_limitations.md)
- [Evaluation journal](docs/evaluation_journal.md)
- [Full milestone ledger](MILESTONES.md)
- [Public alpha guide](docs/public_alpha.md)
- [Outside-user cohort protocol](docs/outside_user_cohort_protocol.md)
- [Evidence workflow](docs/evidence_workflow.md)
- [Evidence intake runbook](docs/evidence_intake_runbook.md)
- [Changelog](CHANGELOG.md)
