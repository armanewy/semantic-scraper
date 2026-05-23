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
- Local model evaluation with JSONL output and failure artifacts is included.
- Optional local Ollama candidate chooser is included.
- Optional Playwright rendering is included for JavaScript pages.
- Replayable rendered-page snapshots and real-page canary evaluation are included.
- Tiny offline candidate-ranker dataset, training, calibration, and runtime policies are included.

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

Evaluate the model locator against the fixture corpus:

```bash
semscrape eval-model fixtures/**/*.yml \
  --models qwen3:1.7b gemma3:1b \
  --top-k 40 \
  --out runs/model-eval.jsonl
```

Use the no-LLM baseline to validate the harness without Ollama:

```bash
semscrape eval-model fixtures/**/*.yml --models heuristic --top-k 40
```

The eval command writes one JSONL row per field, page, and model. When a row fails, it writes debug artifacts under `runs/failures/`: the HTML, prompt metadata, ranked candidates, and model result.

Run conservative strict mode when false positives matter more than coverage:

```bash
semscrape eval-model fixtures/**/*.yml \
  --models heuristic \
  --top-k 40 \
  --strict \
  --out runs/heuristic-strict.jsonl
```

Strict mode abstains unless the selected candidate clears confidence, margin, validator-confidence, and hard-disqualifier gates.

Run the safe local production policy:

```bash
semscrape extract SPEC INPUT \
  --policy safe-local \
  --learn
```

`safe-local` uses cached selectors first, then conservative strict heuristics, and only calls `qwen3:1.7b` after heuristic abstention. Model choices still have to pass validation and strict gates before they can be learned.

Capture a replayable rendered-page snapshot:

```bash
semscrape snapshot SPEC https://example.com/product \
  --out corpus/real/product_001 \
  --wait-for body \
  --screenshot \
  --candidates \
  --accessibility
```

The snapshot command writes `spec.yml`, `url.txt`, `static.html`, `rendered.html`, `metadata.json`, optional `screenshot.png`, optional `accessibility.json`, `candidates.json`, and `extraction.json`. Candidate rows include rendered-page metadata such as visibility, bounding box, computed display/visibility, ARIA role/name, viewport presence, and z-index when the input is a live URL.

Run a replayable real-page canary corpus:

```bash
semscrape canary corpus/real/**/spec.yml \
  --policy safe-local \
  --out runs/real-canary.jsonl \
  --failures-dir runs/failures-real-canary
```

Canary specs can point to a live `url:` in the spec, but replay is the default: if a sibling `rendered.html` exists, canary uses it unless you pass `--live`. For repo-safe tests, a manifest can also point at local replay HTML:

```bash
semscrape canary corpus/repro_minimized/manifest.yml \
  --policy conservative \
  --out runs/repro-canary.jsonl
```

The canary summary reports render failures, timeout rate, cache hit/rejection rates, selector reuse, hidden-candidate rejection rate, and the same safe-local extraction metrics used by model evaluation.

Measure selector reuse with a learn pass followed by a replay pass:

```bash
semscrape canary corpus/repro_minimized/manifest.yml \
  --policy conservative \
  --learn \
  --cache-dir runs/repro-cache \
  --out runs/repro-learn-pass1.jsonl

semscrape canary corpus/repro_minimized/manifest.yml \
  --policy conservative \
  --cache-dir runs/repro-cache \
  --out runs/repro-learn-pass2.jsonl
```

Summarize failure artifacts or a JSONL run:

```bash
semscrape failures summarize runs/failures-real-canary
semscrape failures summarize runs/real-canary.jsonl
```

Run the selector-memory hardening benchmark:

```bash
semscrape canary corpus/repro_minimized/manifest.yml \
  --policy safe-local \
  --learn \
  --cache-dir runs/m6d-cache \
  --out runs/m6d-pass1.jsonl

semscrape canary corpus/repro_minimized/manifest.yml \
  --policy safe-local \
  --cache-dir runs/m6d-cache \
  --out runs/m6d-pass2.jsonl

semscrape compare runs/m6d-pass1.jsonl runs/m6d-pass2.jsonl \
  --left-label pass1 \
  --right-label pass2 \
  --out runs/m6d-compare.md
```

Selector cache entries are structured records with strategy labels, quality scores, success/failure counters, and rejection reasons. The cache format is intentionally strict because the project is still pre-release.

Run the cross-version drift memory benchmark:

```bash
semscrape canary corpus/repro_minimized/manifest-drift-v1.yml \
  --policy safe-local \
  --learn \
  --cache-dir runs/m6e-cache \
  --out runs/m6e-learn-v1.jsonl

semscrape canary corpus/repro_minimized/manifest-drift-v2.yml \
  --policy safe-local \
  --cache-dir runs/m6e-cache \
  --out runs/m6e-test-v2.jsonl

semscrape compare runs/m6e-learn-v1.jsonl runs/m6e-test-v2.jsonl \
  --left-label learn-v1 \
  --right-label test-v2 \
  --cross-version \
  --out runs/m6e-compare.md
```

Generate a single drifted replay HTML file:

```bash
semscrape drift input.html \
  --profile changed_classes \
  --out drifted.html
```

Sweep strict-mode thresholds to find the best coverage at a target false-positive rate:

```bash
semscrape calibrate fixtures/**/*.yml \
  --models heuristic \
  --top-k 40 \
  --out runs/calibration.jsonl
```

Generate a Markdown report from eval or calibration output:

```bash
semscrape report runs/calibration.jsonl --out runs/calibration.md
```

Build a tiny offline candidate ranker from replay fixtures:

```bash
semscrape dataset build corpus/repro_minimized/manifest-drift-v1.yml \
  corpus/repro_minimized/manifest-drift-v2.yml \
  --top-k 40 \
  --out data/candidate-ranking.jsonl

semscrape dataset split data/candidate-ranking.jsonl \
  --by group \
  --train-out data/train.jsonl \
  --test-out data/test.jsonl

semscrape ranker train data/train.jsonl \
  --out models/candidate-ranker.json

semscrape ranker eval data/test.jsonl \
  --model models/candidate-ranker.json \
  --out runs/ranker-eval.jsonl

semscrape ranker calibrate data/test.jsonl \
  --model models/candidate-ranker.json \
  --target-fpr 0.02 \
  --out runs/ranker-calibration.jsonl

semscrape canary corpus/repro_minimized/manifest-drift-v2.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker.json \
  --out runs/ranker-local.jsonl

semscrape canary corpus/repro_minimized/manifest-drift-v2.yml \
  --policy ranker-plus-llm \
  --ranker models/candidate-ranker.json \
  --model qwen3:1.7b \
  --out runs/ranker-plus-llm.jsonl
```

`ranker-local` uses no LLM calls. The ranker path is gated separately from the heuristic path: ranker confidence, ranker margin, validator confidence, hard disqualifiers, penalty count, hidden/visibility checks, and field-aware traps for title/summary/author/coupon/date/monthly-price cases must pass before extraction is accepted. `ranker-plus-llm` only calls the LLM after safe ranker abstentions; unsafe ranker choices abstain instead of asking the LLM to approve them.

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
  "action": "choose",
  "candidate_id": "c0042",
  "confidence": 0.83,
  "reason": "This candidate is labeled as the current sale price."
}
```

or:

```json
{
  "action": "abstain",
  "candidate_id": null,
  "confidence": 0.34,
  "reason": "Multiple plausible prices and no current-price label."
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
semscrape eval-model SPEC_OR_GLOB [INPUT...] --models MODEL... --top-k 40 [--strict]
semscrape calibrate SPEC_OR_GLOB [INPUT...] --models MODEL... --top-k 40
semscrape report RUN_JSONL --out REPORT.md
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
  decision.py    strict confidence/abstention gates
  dom.py         HTML -> compact candidate elements
  eval_model.py  local model evaluation harness
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
  test_eval_model.py
  test_extract_no_llm.py
  test_selectors.py
  test_validators.py

fixtures/
  product/simple_card/
  article/news_article/
  listings/search_results/
  tables/pricing_table/
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

Status: evaluation harness implemented, needs local model bakeoff.

Goal: Let a small local model choose from top-K candidates when deterministic confidence is weak or cached selectors fail.

Implemented:

- `OllamaLocator` using `/api/chat`.
- JSON-schema response format.
- Confidence threshold.
- Validation fallback.
- `eval-model` command.
- Per-field JSONL rows.
- Failure corpus artifacts.
- Hard fixture corpus with distractors, changed layouts, missing fields, listings, articles, and tables.

Acceptance criteria:

```text
candidate_recall@40 >= 95%
model_choice_accuracy_when_candidate_present >= 90%
validated_accuracy >= 90%
false_positive_rate <= 2%
```

Next work:

- Run model bakeoff: `qwen3:1.7b`, `gemma3:1b`, `llama3.2:1b`.
- Compare failure artifacts to classify candidate misses, model mistakes, validator leaks, and ambiguous specs.

### Milestone 4 — Selector repair cache

Status: done.

Goal: Once a field is found, persist the repaired selector so future runs are fast and deterministic.

Implemented:

- `--learn` writes `SPEC.lock.json` by default.
- Cached selectors are tried first.
- Cached values must still pass validation.
- Broken selectors fall through to candidate repair.

### Milestone 4B — Confidence gating and abstention

Status: implemented.

Goal: Avoid silently wrong extractions by making conservative abstention a first-class result.

Implemented:

- Validator reasons, penalties, and hard disqualifiers.
- Field-specific negative evidence for prices, ratings, titles, and dates.
- Strict decision gate with `--strict`, `--min-confidence`, `--min-margin`, and `--min-validator-confidence`.
- `status: abstained` extraction results with reason codes.
- Eval summaries split coverage, misses, abstentions, model errors, and false positives.
- Threshold calibration sweep.
- Markdown reports for eval and calibration runs.

Target:

```text
strict heuristic false_positive_rate <= 5%
LLM strict false_positive_rate <= heuristic strict
LLM strict coverage >= heuristic strict
```

### Milestone 5 — Local model bakeoff and threshold calibration

Status: calibration/report tooling implemented, needs local Ollama models.

Goal: Determine whether local models recover coverage from strict-mode abstentions without reintroducing false positives.

Implemented:

- `eval-model --strict` for local model bakeoffs.
- `calibrate` threshold sweeps for confidence, margin, and validator gates.
- `calibrate --from-jsonl` to reuse existing model eval output without calling models again.
- `report` for Markdown summaries.

Targets:

```text
Good: coverage >= 45% with false_positive_rate <= 2%
Great: coverage >= 60% with false_positive_rate <= 2%
Excellent: coverage >= 70% with false_positive_rate <= 2%
```

### Milestone 6 — Rendered pages

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

### Milestone 7 — Tiny model or classifier

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
