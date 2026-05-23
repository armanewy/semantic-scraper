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

This repo is a developer-alpha semantic scraper CLI:

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
- A packaged default ranker is included, so `ranker-local` works without Ollama or an explicit `--ranker` path.
- Local SQLite evidence capture, review, labeling, privacy-safe export, and evidence-derived dataset generation are included.
- Privacy-audited evidence bundles and maintainer-side bundle intake are included for opt-in contribution workflows.
- A local ecommerce domain-pack skeleton is included for pack-specific ranker and threshold defaults.

The Ollama integration is implemented and has been validated locally with `qwen3:1.7b`. The CLI talks to the running Ollama daemon over its local HTTP API, so the `ollama` executable does not need to be on `PATH` for extraction once the daemon is running.

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

Check the local install:

```bash
semscrape doctor
semscrape ranker info
```

Extract with the packaged offline ranker:

```bash
semscrape extract examples/product.yml examples/product_v2.html --values-only
```

Use the ecommerce pack to apply pack-specific defaults:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --pack ecommerce \
  --values-only
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

Use script-friendly required-field gates:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --require-fields title price availability \
  --fail-on-abstain \
  --min-coverage 0.75
```

Create a small starter project:

```bash
semscrape init product-scraper
cd product-scraper
semscrape extract spec.yml inputs/example.html --policy ranker-local --values-only
```

Exit codes for alpha scripting:

```text
0 = extraction/check succeeded
1 = extraction completed, but required fields or minimum coverage failed
2 = config/spec/runtime error
3 = reserved for render/network errors
4 = model or ranker unavailable
```

Record extraction evidence locally:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --values-only

semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --limit 5

semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
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
  --llm-fallback-policy recoverable-only \
  --out runs/ranker-plus-llm.jsonl

semscrape fallback audit runs/ranker-plus-llm.jsonl \
  --out runs/fallback-audit.md

semscrape canary corpus/ood/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker.json \
  --out runs/ood-ranker-local.jsonl

semscrape canary corpus/ood/manifest.yml \
  --policy ranker-plus-llm \
  --ranker models/candidate-ranker.json \
  --model qwen3:1.7b \
  --out runs/ood-ranker-plus-llm.jsonl

semscrape report-domain runs/ood-ranker-local.jsonl runs/ood-ranker-plus-llm.jsonl \
  --out runs/domain-envelope.md
```

`ranker-local` uses no LLM calls. The ranker path is gated separately from the heuristic path: ranker confidence, ranker margin, validator confidence, hard disqualifiers, penalty count, hidden/visibility checks, and field-aware traps for title/summary/author/coupon/date/monthly-price cases must pass before extraction is accepted. `ranker-plus-llm` only calls the LLM after safe ranker abstentions; unsafe ranker choices abstain instead of asking the LLM to approve them. Its default fallback policy is `recoverable-only`, which suppresses qwen calls unless a visible candidate can plausibly pass the strict gate if selected.

## Evidence Loop

Evidence capture is opt-in and local by default:

```bash
semscrape canary corpus/ood_holdout/manifest.yml \
  --policy ranker-local \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --out runs/ood-holdout.jsonl
```

Review and label records:

```bash
semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db --status abstained --limit 20
semscrape evidence review .semscrape/evidence.db \
  --status abstained \
  --limit 20 \
  --write-review-file review.jsonl

semscrape evidence label .semscrape/evidence.db 123 --correct-candidate c0017
semscrape evidence label .semscrape/evidence.db 124 --correct-value "$59.99"
semscrape evidence label .semscrape/evidence.db 125 --abstention-correct

semscrape evidence apply-review .semscrape/evidence.db review.jsonl
```

Export privacy-controlled evidence and turn it into ranker data:

```bash
semscrape evidence export .semscrape/evidence.db \
  --only-labeled \
  --min-trust silver \
  --privacy features-only \
  --out data/evidence-labeled.jsonl

semscrape dataset build \
  --from-evidence data/evidence-labeled.jsonl \
  --out data/candidate-ranking-v3.jsonl

semscrape ranker model-card models/candidate-ranker-v3.json \
  --out models/candidate-ranker-v3.md
```

Privacy modes:

```text
full          keeps candidate values/text/context for local debugging
redacted      keeps candidate values and ML features, replaces long text/context with hashes
features-only keeps labels and ML features, omits raw values/text/context/selectors
```

Trust levels control which labels can feed release-candidate training:

```text
gold       explicit user corrections, manually reviewed labels, benchmark/canary expected values
silver     confirmed fallback or repeated validated canary evidence
bronze     high-confidence production evidence without ground truth
untrusted  unknown production outputs
```

Global-training exports default to `--min-trust silver`, so bronze and untrusted production positives are excluded unless explicitly requested.

Create an opt-in contribution bundle and audit it before sharing:

```bash
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --min-trust silver \
  --out semscrape-evidence-bundle.zip

semscrape evidence audit semscrape-evidence-bundle.zip
```

Maintainer-side intake validates privacy, schema version, and duplicate records before writing merged evidence:

```bash
semscrape evidence intake bundles/*.zip \
  --out data/intake/evidence.jsonl
```

Features-only bundles include `manifest.json`, `records.jsonl`, `schema.json`, `privacy_report.json`, and `summary.json`. The privacy audit rejects bundles that contain raw HTML, selectors, full candidate text, or raw values unless values are explicitly allowed.

Run the M10 base-ranker release-candidate workflow:

```bash
semscrape dataset build corpus/base_train/manifest.yml corpus/base_dev/manifest.yml \
  --top-k 40 \
  --out data/candidate-ranking-v3.jsonl

semscrape ranker train data/candidate-ranking-v3.jsonl \
  --out models/candidate-ranker-v3.json

semscrape canary corpus/base_holdout/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker-v2.json \
  --out runs/m10/base-holdout-v2.jsonl

semscrape canary corpus/base_holdout/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker-v3.json \
  --out runs/m10/base-holdout-v3.jsonl

semscrape canary corpus/adversarial_holdout/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker-v3.json \
  --out runs/m10/adversarial-holdout-v3.jsonl

semscrape ranker release-check \
  --baseline runs/m10/base-holdout-v2.jsonl \
  --candidate runs/m10/base-holdout-v3.jsonl \
  --adversarial runs/m10/adversarial-holdout-v3.jsonl \
  --out runs/m10/release-check.json
```

`corpus/base_holdout/` and `corpus/adversarial_holdout/` are sealed release-candidate suites. Do not include them in dataset builds, evidence-derived training exports, or ranker tuning. `candidate-ranker-v3` is the current packaged default because it passed the M10 release check; keep `candidate-ranker-v2` for regression comparisons.

## Domain Packs

Domain packs bundle a ranker artifact, policy defaults, threshold presets, validator notes, supported fields, and a model card for a page family:

```text
packs/
  ecommerce/
    pack.yml
    thresholds.yml
    validators.yml
    supported-fields.yml
    model-card.md
```

Use a pack with any command that supports extraction policy defaults:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --pack ecommerce \
  --values-only

semscrape canary corpus/base_holdout/manifest.yml \
  --pack ecommerce \
  --out runs/ecommerce-holdout.jsonl
```

The initial `ecommerce` pack resolves to the packaged default ranker and conservative `ranker-local` thresholds. Packs are local files today; they are the foundation for future domain-specific rankers, validators, thresholds, and model cards.

## Alpha Pilots And Pack Releases

Pilot projects are local external-style usage cases. A pilot run executes a manifest, records evidence, creates a privacy-safe bundle, audits it, and writes summary/report artifacts:

```bash
semscrape pilot run pilots/ecommerce_alpha_001 --pack ecommerce
semscrape pilot run pilots/articles_alpha_001 --policy ranker-local
semscrape pilot run pilots/listings_alpha_001 --policy ranker-local
```

Generate standardized field-trial reports:

```bash
semscrape pilot report pilots/ecommerce_alpha_001 \
  --out runs/m13/ecommerce-pilot-report.md

semscrape pilot summarize pilots/* \
  --out runs/m13/alpha-pilot-summary.md
```

Generated pilot evidence DBs, bundles, and run outputs are ignored by git. The checked-in pilot directories keep only the manifest, expected values, and instructions.

The local pack release loop is:

```bash
semscrape evidence intake \
  pilots/ecommerce_alpha_001/evidence-bundle.zip \
  pilots/articles_alpha_001/evidence-bundle.zip \
  pilots/listings_alpha_001/evidence-bundle.zip \
  --out runs/m12/pilot-intake.jsonl

semscrape pack build ecommerce \
  --from-intake runs/m12/pilot-intake.jsonl \
  --out packs/ecommerce-v1

semscrape pack release-check packs/ecommerce-v1 \
  --baseline packs/ecommerce \
  --holdout corpus/base_holdout/manifest.yml \
  --adversarial corpus/adversarial_holdout/manifest.yml \
  --out runs/m12/ecommerce-v1-release-check.json

semscrape pack compare packs/ecommerce packs/ecommerce-v1 \
  --out runs/m12/ecommerce-pack-compare.md
```

`pack release-check` runs baseline and candidate packs against the sealed base holdout, then runs the candidate against the adversarial holdout. Promotion requires no false-positive regression, adversarial false-positive rate of zero, model-call rate of zero, feature-schema compatibility, and a model card.

Analyze incoming pilot evidence for pack gaps:

```bash
semscrape pack gaps runs/m13/pilot-intake.jsonl \
  --pack ecommerce \
  --out runs/m13/ecommerce-gaps.md
```

The pilot playbook for external alpha users is in [docs/alpha_pilot_playbook.md](docs/alpha_pilot_playbook.md).

The first external-style alpha execution intentionally used the frozen `v0.1.0-alpha.1` target. It proved that the evidence/privacy loop worked, but failed the field-trial safety gate because unseen page semantics produced false positives. M13R remediated those incidents with narrow deterministic gates and validators, then reran the original pilots and a new mini-holdout with zero observed false positives. The incident report is in [docs/m13r_false_positive_incident_report.md](docs/m13r_false_positive_incident_report.md).

Run the M8C OOD hardening workflow:

```bash
semscrape dataset build corpus/repro_minimized/manifest-drift-v1.yml \
  corpus/repro_minimized/manifest-drift-v2.yml \
  corpus/ood_dev/manifest.yml \
  --top-k 40 \
  --out data/candidate-ranking-v2.jsonl

semscrape dataset split data/candidate-ranking-v2.jsonl \
  --by group \
  --train-out data/train-v2.jsonl \
  --test-out data/test-v2.jsonl

semscrape ranker train data/train-v2.jsonl \
  --out models/candidate-ranker-v2.json

semscrape canary corpus/ood_dev/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker-v2.json \
  --max-ranker-penalties 1 \
  --out runs/m8c-dev-ranker-local.jsonl

semscrape canary corpus/ood_holdout/manifest.yml \
  --policy ranker-local \
  --ranker models/candidate-ranker-v2.json \
  --max-ranker-penalties 1 \
  --out runs/m8c-holdout-ranker-local.jsonl

semscrape canary corpus/ood_holdout/manifest.yml \
  --policy ranker-plus-llm \
  --ranker models/candidate-ranker-v2.json \
  --max-ranker-penalties 1 \
  --model qwen3:1.7b \
  --out runs/m8c-holdout-ranker-plus-llm.jsonl
```

`corpus/ood_dev/` is allowed to influence ranker training and targeted gates. `corpus/ood_holdout/` is a sealed replay holdout; do not include it in dataset builds or ranker training.

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

Status: calibration/report tooling implemented and validated locally with Ollama models.

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
