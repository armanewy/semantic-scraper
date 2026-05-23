# semscrape

A local-first semantic scraper CLI.

The goal is not to call an LLM for every scraped value. The goal is to keep scraping cheap and deterministic most of the time, then use a small local model only when selectors drift or the DOM changes enough that cached extraction fails.

```text
cached selector
  -> validate value
  -> if broken, generate compact DOM candidates
  -> rank candidates deterministically
  -> optionally ask a local Ollama model to choose one candidate ID
  -> validate the chosen value
  -> persist repaired selector
```

## Why this exists

Traditional scrapers bind to brittle structure:

```css
.product-card > div:nth-child(2) > span.price
```

A semantic scraper should bind to intent:

```yaml
name: price
description: Current sale price, not the old/list/strikethrough price.
```

Then it should regenerate a deterministic selector once it finds the right element.

## Current status

This repo is a working milestone-1/milestone-2 project:

- Static HTML extraction works.
- Deterministic candidate ranking works.
- Validators for text, price, number, date, URL, email, and bool are included.
- Selector repair cache is included.
- Mutation testing is included.
- Candidate recall testing is included.
- Optional local Ollama candidate chooser is included.
- Optional Playwright rendering is included for JavaScript pages.

The Ollama integration is implemented but should be validated on your machine because this sandbox does not run an Ollama daemon.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For development:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

For rendered pages:

```bash
python -m pip install -e ".[render]"
playwright install chromium
```

## Quick demo

Extract from two structurally different product pages without an LLM:

```bash
semscrape extract examples/product.yml examples/product_v1.html --no-llm --values-only
semscrape extract examples/product.yml examples/product_v2.html --no-llm --values-only
```

Expected output for `product_v2.html`:

```json
{
  "title": "AeroPress Go Travel Coffee Press",
  "price": "$59.99",
  "rating": "4.7",
  "availability": "Available now"
}
```

Run the benchmark:

```bash
semscrape benchmark examples/product.yml examples/product_v1.html examples/product_v2.html --no-llm
```

Generate mutated pages and test candidate recall:

```bash
semscrape mutate examples/product_v1.html --out mutations --n 20 --seed 7
semscrape recall examples/product.yml mutations/*.html --expect-like product_v1.html --top-k 40
semscrape benchmark examples/product.yml mutations/*.html --expect-like product_v1.html --no-llm
```

## Local LLM usage

Install and run Ollama separately, then pull a small model:

```bash
ollama pull qwen3:1.7b
```

Run extraction with local model repair:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --model qwen3:1.7b \
  --learn
```

The model is not asked to scrape arbitrary text. It receives a bounded top-K list of DOM candidates and must return strict JSON:

```json
{
  "candidate_id": "c0042",
  "confidence": 0.83,
  "reason": "This candidate is labeled as the current sale price."
}
```

The chosen candidate is still validated. If it fails validation or confidence is too low, the CLI falls back to deterministic ranking.

## Spec format

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
  product_v1.html:
    price: "$59.99"
```

Supported field types:

```text
text, price, number, date, url, email, bool
```

Supported validators:

```text
min_length, max_length, regex, regex_not, contains, not_contains, choices, require_currency
```

## CLI commands

```bash
semscrape extract SPEC INPUT [--no-llm] [--learn] [--model MODEL]
semscrape inspect SPEC INPUT FIELD --top-k 20
semscrape benchmark SPEC INPUT... [--expect-like BASENAME]
semscrape recall SPEC INPUT... --top-k 40 [--expect-like BASENAME]
semscrape mutate INPUT --out DIR --n 20 --seed 7
semscrape cache-clear CACHE_PATH
```

Inputs can be local files or URLs. For URLs that need JavaScript rendering, use:

```bash
semscrape extract examples/product.yml https://example.com/item --render --wait-for "h1"
```

## Project layout

```text
src/semscrape/
  cache.py       selector memory / lock files
  cli.py         command line entrypoint
  dom.py         HTML -> compact candidate elements
  extract.py     extraction and repair loop
  heuristics.py  deterministic ranking
  llm.py         local Ollama candidate chooser
  mutate.py      HTML drift generator
  render.py      requests + optional Playwright rendering
  selectors.py   CSS selector generation
  spec.py        YAML spec loader
  validators.py  type-specific scalar validators

examples/
  product.yml
  product_v1.html
  product_v2.html
  article.yml
  article_v1.html

tests/
  test_candidate_generation.py
  test_extract_no_llm.py
  test_selectors.py
  test_validators.py
```

## Milestones

### Milestone 1 — Static semantic extraction

Status: done.

Goal: Given HTML and a field spec, produce the correct scalar value without using brittle prewritten selectors.

Implemented:

- DOM candidate generation.
- Compact candidate contexts.
- Field-specific validators.
- Heuristic ranker.
- `extract`, `inspect`, and `benchmark` commands.

Success test:

```bash
python -m pytest -q
semscrape benchmark examples/product.yml examples/product_v1.html examples/product_v2.html --no-llm
```

### Milestone 2 — Robustness harness

Status: done.

Goal: Measure candidate recall before measuring LLM quality.

Implemented:

- `mutate` command that changes classes/IDs/wrappers and injects distractors.
- `recall` command that checks whether expected values appear in top-K candidates.
- `benchmark --expect-like` for mutated copies.

The key metric is candidate recall@K:

```text
Did the correct element/value appear in the top 40 candidates?
```

If recall is poor, no LLM can reliably fix the scraper.

### Milestone 3 — Local model chooser

Status: implemented, needs local-machine evaluation.

Goal: Let a small local model choose from top-K candidates when deterministic confidence is weak or cached selectors fail.

Implemented:

- `OllamaLocator` using `/api/chat`.
- JSON-schema response format.
- Confidence threshold.
- Validation fallback.

Next work:

- Run model bakeoff: `qwen3:1.7b`, `gemma3:1b`, `llama3.2:1b`.
- Store model mistakes in a failure corpus.
- Add a CLI command that compares model choices against expected candidates.

### Milestone 4 — Selector repair cache

Status: done.

Goal: Once a field is found, persist the repaired selector so future runs are fast and deterministic.

Implemented:

- `--learn` writes `SPEC.lock.json` by default.
- Cached selectors are tried first.
- Cached values must still pass validation.
- Broken selectors fall through to candidate repair.

### Milestone 5 — Rendered pages

Status: first pass implemented.

Goal: Support JavaScript-rendered pages.

Implemented:

- URL fetching with `requests`.
- Optional Playwright rendering with `--render`.
- Optional `--wait-for` selector.

Next work:

- Snapshot accessibility tree.
- Include element coordinates and computed visibility.
- Support iframes.
- Add login/session storage.

### Milestone 6 — Tiny model or classifier

Status: not started.

Goal: Replace or complement generic Ollama models with a small specialized ranker.

Potential path:

- Generate labeled data from specs and fixtures.
- Train a pairwise ranker or token classifier.
- Use the local LLM only as a teacher/data generator.
- Ship a small ONNX/gguf model for candidate reranking.

## Design rules

1. Do not use an LLM on every page unless explicitly requested.
2. Always validate values after model selection.
3. Cache selectors only as a fast path, never as permanent truth.
4. Measure candidate recall before model accuracy.
5. Prefer deterministic extraction whenever confidence is high.
6. Keep the CLI useful by itself before building SaaS features.

## What is not included yet

- CAPTCHA solving.
- Proxy rotation.
- Anti-bot bypassing.
- Full browser session management.
- Multi-page crawling workflows.
- Fine-tuned local model.
- Visual/coordinate-aware candidate ranking.

Those are later product layers. The first thing to prove is that a local semantic locator can survive DOM drift.
