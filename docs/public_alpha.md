# Public Alpha

`v0.1.0-alpha.7` is a limited public-alpha cohort candidate for local, repeatable extraction workflows.

The default posture is conservative:

```text
policy: ranker-local-safe
LLM calls: disabled by default
goal: abstain when evidence is weak
```

semscrape is not trying to call an LLM for every scraped value. It generates bounded DOM candidates, ranks them locally, validates the selected value, and abstains when the evidence does not clear the safety gates.

Alpha.7 is intentionally more conservative than alpha.6. The founder-operated external cohort found false positives and one features-only privacy leak on alpha.6; alpha.7 remediates those issues and should be used for the next true outside-user cohort.

## Install

```bash
git clone https://github.com/armanewy/semantic-scraper.git
cd semantic-scraper
python -m pip install -e ".[dev]"
```

Check the local install:

```bash
semscrape doctor
semscrape ranker info
```

## First Run

Create a small local project:

```bash
semscrape init my-scraper
cd my-scraper
```

Inspect candidates before tuning thresholds:

```bash
semscrape inspect spec.yml inputs/example.html price
```

Run extraction:

```bash
semscrape extract spec.yml inputs/example.html --values-only
```

Run a replay canary:

```bash
semscrape canary manifest.yml --record-evidence --out runs/canary.jsonl
```

## Evidence Bundle

Create and audit a privacy-safe evidence bundle:

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
```

Features-only bundles are designed to omit raw HTML, selectors, full candidate text, and raw values.

## When Extraction Abstains

An abstention is an intended safety behavior. Use:

```bash
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
semscrape inspect spec.yml inputs/example.html FIELD_NAME
```

If the correct candidate is not in the top candidates, the next fix is candidate generation/spec clarity, not ranker threshold loosening.

## When A Value Is Wrong

False positives are the highest-priority alpha incident. Please include:

- field name
- expected value
- actual value
- policy
- ranker version from `semscrape ranker info`
- whether the correct value appeared in `inspect` or candidate recall
- an audited features-only evidence bundle when possible

Do not train on unverified accepted outputs as positive labels.

## Optional Local LLM

Ollama fallback remains optional:

```bash
semscrape extract spec.yml inputs/example.html \
  --policy ranker-plus-llm \
  --model qwen3:1.7b
```

The local model is a fallback for recoverable abstentions, not the default extraction engine.
