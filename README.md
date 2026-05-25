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

This repo is a controlled public-alpha semantic scraper CLI:

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
- A high-precision `ranker-local-safe` policy is included for public-alpha style runs where abstention is preferred over false positives.
- Local SQLite evidence capture, review, labeling, privacy-safe export, and evidence-derived dataset generation are included.
- Privacy-audited evidence bundles and maintainer-side bundle intake are included for opt-in contribution workflows.
- A local ecommerce domain-pack skeleton is included for pack-specific ranker and threshold defaults.

Current release state:

```text
M16F: passed
M16C local stand-in cohort: passed safety
M16C founder-operated external cohort on alpha.6: failed safety/privacy
M16R-Founder: passed
M16U safe coverage recovery: passed
v0.1.0-alpha.8: safety-remediated, coverage-recovered outside-cohort target
M16W founder-operated wide external corpus: executed, failed safety/recall
M16W-R wide corpus recall and missing-candidate safety: passed
v0.1.0-alpha.9: next frozen true outside-user cohort target after tagging
M17 automated external evidence harvester tooling: implemented
M17S automated harvester scale run: passed
v0.1.0-alpha.10: frozen harvester-scale target
M18 review queue triage and trusted label conversion: implemented
M18B trusted label acquisition / oracle sources: passed
M19 evidence-driven ranker/pack update: completed, no promotion
M19R ranker update diagnostics: completed, no promotion
M20 safety veto + positive label expansion: completed, opt-in veto added
M16C true outside-user cohort: pending
```

The corrected M16C local stand-in cohort result was:

```text
bundles:                25
fields_attempted:       69
coverage_rate:          0.753623
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
abstention_rate:        0.246377
bundle_audit_pass_rate: 1.000000
```

That was preflight evidence, not a completed outside-user field trial. A broader founder-operated external cohort then found that `v0.1.0-alpha.6` was still too aggressive on fresh pages:

```text
coverage_rate:          0.986667
false_positive_rate:    0.333333
candidate_recall@40:    0.933333
bundle_audit_pass_rate: 0.937500
```

M16R-Founder fixed the features-only privacy leak, added narrower safety gates for repeated lists, docs navigation/title contexts, table row/column fields, and generic text overmatches, and made `ranker-local-safe` more conservative. The remediation rerun result was:

```text
founder_external_remediation:
  fields_attempted:       91
  coverage_rate:          0.296703
  false_positive_rate:    0.000000
  candidate_recall@40:    0.989011
  abstention_rate:        0.703297
  bundle_audit_pass_rate: 1.000000

fresh_mini_holdout:
  fields_attempted:       22
  coverage_rate:          0.318182
  false_positive_rate:    0.000000
  candidate_recall@40:    1.000000
  bundle_audit_pass_rate: 1.000000
```

The alpha.7 coverage drop was intentional: it restored abstention as the safety default, but it was too quiet for a useful outside-user alpha. M16U recovered coverage with a narrow safe acceptance ladder for structurally grounded low-margin ranker choices:

```text
founder_external_m16u:
  fields_attempted:       91
  coverage_rate:          0.769231
  false_positive_rate:    0.000000
  candidate_recall@40:    0.989011
  bundle_audit_pass_rate: 1.000000

fresh_mini_holdout_m16u:
  fields_attempted:       27
  coverage_rate:          0.555556
  false_positive_rate:    0.000000
  candidate_recall@40:    0.962963
  bundle_audit_pass_rate: 1.000000
```

At that point, the next gate was a true outside-user cohort on the frozen `v0.1.0-alpha.8` tag.

Before inviting true outside users, M16W widened founder-operated validation to 54 projects, 14 source groups, and 267 attempted fields. Privacy and coverage passed, but false-positive rate and candidate recall failed:

```text
coverage_rate:          0.629213
false_positive_rate:    0.026217
candidate_recall@40:    0.850187
bundle_audit_pass_rate: 1.000000
```

The M16W report is in [docs/m16w_founder_wide_report.md](docs/m16w_founder_wide_report.md). M16C true outside-user testing remains blocked until M16W-R remediates candidate recall and extracted-wrong behavior on missing candidates.

M16W-R remediated the wide-corpus blocker. The main fixes were metadata candidates, fast sibling-aware structural selectors, first-section and repeated-card ordinal safety, paragraph-specific evidence, quote/product safe recovery, document-title head-only gating, and removal of invalid generated expected-value rows from the remediation measurement set:

```text
founder_wide_remediation:
  fields_attempted:       257
  coverage_rate:          0.692607
  false_positive_rate:    0.000000
  candidate_recall@40:    1.000000
  bundle_audit_pass_rate: 1.000000

fresh_wide_mini_holdout:
  projects/pages:         16
  source_groups:          7
  fields_attempted:       61
  coverage_rate:          0.721311
  false_positive_rate:    0.000000
  candidate_recall@40:    1.000000
  bundle_audit_pass_rate: 1.000000
```

Incident reports:

- [M16W-R candidate recall incident report](docs/m16w_r_candidate_recall_incident_report.md)
- [M16W-R false-positive incident report](docs/m16w_r_false_positive_incident_report.md)

The next frozen target after M16W-R is `v0.1.0-alpha.9`.

M17 adds a local automated evidence harvester. It is designed to collect privacy-safe evidence continuously without turning raw extractions into positive training labels:

```bash
semscrape alpha run sources/external.yml \
  --policy ranker-local-safe \
  --privacy features-only \
  --out runs/auto/latest
```

The harvester writes `summary.md`, `intake.jsonl`, `gaps.md`, `review-queue.jsonl`, per-source bundles, and a `harvest-manifest.json`. It enforces split metadata (`dev`, `holdout`, `adversarial`, `monitor_only`, `train_candidate`) and review-oriented trust boundaries. It does not train or promote rankers/packs. See [Automated External Evidence Harvester](docs/automated_evidence_harvester.md).

M17S ran the harvester across 102 public-page replay sources and passed the scale gate: bundle audit pass rate `1.000000`, false-positive rate `0.002155`, and candidate recall@40 `0.995633`. See [M17S Harvester Scale Report](docs/m17s_harvester_scale_report.md).

M18 adds maintainer review commands for converting harvester queue items into trusted labels without poisoning the ranker:

```bash
semscrape review triage runs/auto/latest/review-queue.jsonl --out runs/review/triage.md
semscrape review export runs/auto/latest/review-queue.jsonl --limit 100 --priority high --out runs/review/batch.jsonl
semscrape review apply runs/review/batch-reviewed.jsonl --intake runs/auto/latest/intake.jsonl --out data/review/training-eligible-evidence.jsonl --report runs/review/trust-conversion.json
```

The M18 pass converted the M17S dev-split false positive into one reviewed gold hard-negative training row, classified two candidate misses as candidate-generation issues, and left recoverable abstentions deferred until explicit value review. See [M18 Review Queue Conversion Report](docs/m18_review_queue_conversion_report.md).

M18B adds oracle-backed expected values via `semscrape oracle resolve`, `semscrape oracle report`, and `semscrape alpha run --resolve-oracles`. Supported oracle types are `manual_expected`, `pypi_json`, `npm_registry`, `github_repo`, and `json_ld`. The M18B run generated 98 gold oracle-backed labels and 98 training-eligible evidence rows without using raw extraction guesses as positives. See [M18B Oracle Label Acquisition Report](docs/m18b_oracle_label_acquisition_report.md).

M19 used the M18B oracle labels to build an evidence-derived candidate-ranking dataset with 3,920 rows, 186 positives, and 1,498 hard negatives. A `candidate-ranker-vNext` and `ecommerce-vNext` pack candidate were trained and release-checked. Both kept false positives at zero on the checked suites, but both lost too much coverage, so neither was promoted. The packaged default remains `candidate-ranker-v3`, and the current ecommerce pack remains `packs/ecommerce-v1`. See [M19 Evidence-Driven Ranker/Pack Update Report](docs/m19_evidence_driven_update_report.md).

M19R diagnosed the M19 coverage regression and added `semscrape ranker diff` plus `semscrape dataset balance` for future update attempts. The oracle-trained candidate fixed two oracle-eval false positives but lost correct base/ecommerce rows; a balanced recipe improved base holdout coverage while preserving zero FPR, but still did not clear the release gate. No replacement ranker, pack, or veto policy was promoted. See [M19R Ranker Regression Diagnosis](docs/m19r_ranker_regression_diagnosis.md).

M20 added an internal opt-in `ranker-local-safe-veto` policy and `semscrape ranker veto-eval`. The veto uses `candidate-ranker-v3` for normal extraction and lets `candidate-ranker-vNext` block accepted candidates only when its positive-confidence score is below the veto threshold. On M20 checks it fixed the 2 oracle-eval false positives, preserved base-holdout coverage at `0.450000`, and kept adversarial FPR at `0.000000`. Defaults are unchanged pending broader validation. See [M20 Safety Veto Report](docs/m20_safety_veto_report.md).

M21 calibrated the broad veto and found it too coverage-destructive for promotion. M22 adds the narrower opt-in `ranker-local-safe-trap-veto` policy and `semscrape ranker trap-veto-report` so high-precision trap rules can be evaluated separately from the broad learned veto. Defaults remain unchanged: `candidate-ranker-v3`, `packs/ecommerce-v1`, and `ranker-local-safe`. See [M21 Veto Distillation Report](docs/m21_veto_distillation_report.md) and [M22 Trap-Only Veto Promotion Trial](docs/m22_trap_only_veto_promotion_trial.md).

The Ollama integration is implemented and has been validated locally with `qwen3:1.7b`. The CLI talks to the running Ollama daemon over its local HTTP API, so the `ollama` executable does not need to be on `PATH` for extraction once the daemon is running.

Public-alpha notes:

- [Public alpha guide](docs/public_alpha.md)
- [Known limitations](docs/known_limitations.md)
- [Evidence intake runbook](docs/evidence_intake_runbook.md)
- [Changelog](CHANGELOG.md)

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

Use the public-alpha-safe local policy when false positives matter more than coverage:

```bash
semscrape extract examples/product.yml examples/product_v2.html \
  --policy ranker-local-safe \
  --values-only
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
semscrape extract spec.yml inputs/example.html --policy ranker-local-safe --values-only
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

`ranker-local-safe` is the public-alpha high-precision preset: it uses no LLM calls and tightens ranker confidence, margin, validator-confidence, and penalty gates. `ranker-local` remains available for internal comparison when more coverage is useful. `ranker-local-safe-veto` is an internal opt-in evaluation policy that keeps the baseline safe ranker decision path, then lets a separate safety ranker block accepted candidates below `--veto-confidence-below`; it does not recover candidates and is not the default. The ranker path is gated separately from the heuristic path: ranker confidence, ranker margin, validator confidence, hard disqualifiers, penalty count, hidden/visibility checks, and field-aware traps for title/summary/author/coupon/date/monthly-price cases must pass before extraction is accepted. `ranker-plus-llm` only calls the LLM after safe ranker abstentions; unsafe ranker choices abstain instead of asking the LLM to approve them. Its default fallback policy is `recoverable-only`, which suppresses qwen calls unless a visible candidate can plausibly pass the strict gate if selected.

## Evidence Loop

Evidence capture is opt-in and local by default:

```bash
semscrape canary corpus/ood_holdout/manifest.yml \
  --policy ranker-local-safe \
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

Summarize a controlled alpha cohort from audited bundles:

```bash
semscrape alpha summarize alpha_bundles/*.zip \
  --out runs/m16/public-alpha-summary.md
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

The initial `ecommerce` pack resolves to the packaged default ranker and conservative local thresholds. Packs are local files today; they are the foundation for future domain-specific rankers, validators, thresholds, and model cards.

## Alpha Pilots And Pack Releases

Pilot projects are local external-style usage cases. A pilot run executes a manifest, records evidence, creates a privacy-safe bundle, audits it, and writes summary/report artifacts:

```bash
semscrape pilot run pilots/ecommerce_alpha_001 --pack ecommerce
semscrape pilot run pilots/articles_alpha_001 --policy ranker-local-safe
semscrape pilot run pilots/listings_alpha_001 --policy ranker-local-safe
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

`v0.1.0-alpha.2` is an internal validation tag for the M13R build. It passed the original external-alpha regression suite, but M14 fresh pilots found new false positives and candidate-recall misses, so it was not promoted to public alpha. M14R converted those failures into targeted normalization, region, listing-order, title, and plan-price gates. The remediated fresh-alpha rerun reached `false_positive_rate = 0.0` and `candidate_recall_at_40 = 1.0`; a separate final mini-holdout also stayed at `false_positive_rate = 0.0`. Reports are in [docs/m14_alpha2_validation_report.md](docs/m14_alpha2_validation_report.md) and [docs/m14r_fresh_alpha_incident_report.md](docs/m14r_fresh_alpha_incident_report.md).

`v0.1.0-alpha.3` is the M14R-remediated validation tag. M15 tested it against a larger fresh pilot set and found that known regression suites stayed clean, but fresh-pilot false-positive rate was `0.096774`, so it is not public-alpha ready. The public-readiness report is in [docs/m15_alpha3_public_readiness_report.md](docs/m15_alpha3_public_readiness_report.md).

`v0.1.0-alpha.4` is the M15R safety-remediated extraction tag. It introduced the conservative `ranker-local-safe` public-alpha preset and restored zero observed false positives on the accumulated regression suites. The safety report is in [docs/m15r_public_alpha_safety_report.md](docs/m15r_public_alpha_safety_report.md).

`v0.1.0-alpha.5` added public-alpha onboarding/tooling, but it should not be used for the true outside-user cohort because `alpha summarize` overcounted final abstentions with rejected trace candidates as false positives.

`v0.1.0-alpha.6` fixes that measurement bug. The M16C local stand-in cohort passed safety under corrected final-result metrics:

```text
bundles:                25
fields_attempted:       69
coverage_rate:          0.753623
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
abstention_rate:        0.246377
bundle_audit_pass_rate: 1.000000
```

The founder-operated external cohort then failed safety and privacy on alpha.6:

```text
coverage_rate:          0.986667
false_positive_rate:    0.333333
candidate_recall@40:    0.933333
bundle_audit_pass_rate: 0.937500
```

`v0.1.0-alpha.7` is the M16R-Founder remediation tag. It fixes the features-only raw HTML leak and makes `ranker-local-safe` deliberately conservative:

```text
founder_external_remediation:
  fields_attempted:       91
  coverage_rate:          0.296703
  false_positive_rate:    0.000000
  candidate_recall@40:    0.989011
  bundle_audit_pass_rate: 1.000000

fresh_mini_holdout:
  fields_attempted:       22
  coverage_rate:          0.318182
  false_positive_rate:    0.000000
  candidate_recall@40:    1.000000
  bundle_audit_pass_rate: 1.000000
```

The incident report is in [docs/m16r_founder_external_incident_report.md](docs/m16r_founder_external_incident_report.md). M16U then recovered useful safe-policy coverage without reopening false positives:

```text
founder_external_m16u:
  fields_attempted:       91
  coverage_rate:          0.769231
  false_positive_rate:    0.000000
  candidate_recall@40:    0.989011
  bundle_audit_pass_rate: 1.000000

fresh_mini_holdout_m16u:
  fields_attempted:       27
  coverage_rate:          0.555556
  false_positive_rate:    0.000000
  candidate_recall@40:    0.962963
  bundle_audit_pass_rate: 1.000000
```

The M16U report is in [docs/m16u_safe_coverage_recovery_report.md](docs/m16u_safe_coverage_recovery_report.md). This is still preflight evidence only. M16C remains pending until outside users/projects reproduce the workflow without direct maintainer steering.

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
semscrape doctor
semscrape init PROJECT_DIR
semscrape inspect SPEC INPUT FIELD --top-k 20
semscrape benchmark SPEC INPUT... [--expect-like BASENAME]
semscrape recall SPEC INPUT... --top-k 40 [--expect-like BASENAME]
semscrape eval-model SPEC_OR_GLOB [INPUT...] --models MODEL... --top-k 40 [--strict]
semscrape calibrate SPEC_OR_GLOB [INPUT...] --models MODEL... --top-k 40
semscrape report RUN_JSONL --out REPORT.md
semscrape compare LEFT.jsonl RIGHT.jsonl --out REPORT.md
semscrape report-domain RUN.jsonl [...] --out REPORT.md
semscrape fallback audit RUN.jsonl --out REPORT.md
semscrape mutate INPUT --out DIR --n 20 --seed 7
semscrape drift INPUT --profile PROFILE --out OUTPUT
semscrape snapshot SPEC URL --out DIR [--screenshot] [--candidates] [--accessibility]
semscrape canary SPEC_OR_MANIFEST [...] --policy ranker-local-safe --out RUN.jsonl
semscrape dataset build SPEC_OR_MANIFEST [...] --out DATASET.jsonl
semscrape dataset split DATASET.jsonl --by group --train-out TRAIN.jsonl --test-out TEST.jsonl
semscrape dataset balance DATASET.jsonl --out BALANCED.jsonl
semscrape ranker info [--model RANKER.json]
semscrape ranker train TRAIN.jsonl --out RANKER.json
semscrape ranker eval TEST.jsonl --model RANKER.json --out RUN.jsonl
semscrape ranker veto-eval TEST.jsonl --model BASELINE.json --veto-ranker VETO.json --out RUN.jsonl
semscrape ranker calibrate TEST.jsonl --model RANKER.json --out RUN.jsonl
semscrape ranker model-card RANKER.json --out MODEL_CARD.md
semscrape ranker release-check --baseline BASE.jsonl --candidate CANDIDATE.jsonl --adversarial ADV.jsonl --out CHECK.json
semscrape ranker diff LEFT.jsonl RIGHT.jsonl --out DIFF.jsonl --summary-out DIFF.md
semscrape evidence stats .semscrape/evidence.db
semscrape evidence review .semscrape/evidence.db [--status abstained]
semscrape evidence label .semscrape/evidence.db RECORD_ID --correct-candidate CANDIDATE_ID
semscrape evidence export .semscrape/evidence.db --privacy features-only --out EVIDENCE.jsonl
semscrape evidence bundle .semscrape/evidence.db --privacy features-only --out bundle.zip
semscrape evidence audit bundle.zip
semscrape evidence intake bundles/*.zip --out intake.jsonl
semscrape pilot run PROJECT_DIR --policy ranker-local-safe --record-evidence
semscrape pilot report PROJECT_DIR --out report.md
semscrape pilot summarize pilots/* --out summary.md
semscrape alpha summarize alpha_bundles/*.zip --out runs/m16/public-alpha-summary.md
semscrape pack info ecommerce
semscrape pack build ecommerce --from-intake intake.jsonl --out packs/ecommerce-v1
semscrape pack release-check packs/ecommerce-v1 --baseline packs/ecommerce --holdout HOLDOUT.yml --adversarial ADV.yml --out CHECK.json
semscrape pack compare packs/ecommerce packs/ecommerce-v1 --out compare.md
semscrape pack gaps intake.jsonl --pack ecommerce --out gaps.md
semscrape failures summarize RUN_OR_FAILURE_DIR
semscrape cache-clear CACHE_PATH
```

Inputs can be local files or URLs. For URLs that need JavaScript rendering, use:

```bash
semscrape extract examples/product.yml https://example.com/item --render --wait-for "h1"
```

## Project layout

```text
src/semscrape/
  assets.py      packaged ranker lookup
  cache.py       selector memory / lock files
  cli.py         command line entrypoint
  dataset.py     candidate-ranking dataset build/split
  decision.py    strict confidence/abstention gates
  dom.py         HTML -> compact candidate elements
  drift.py       named replay drift generator
  eval_model.py  local model/eval/report metrics
  evidence.py    SQLite evidence store, bundles, intake, privacy audit
  extract.py     extraction, ranker, LLM fallback, and repair loop
  heuristics.py  deterministic candidate ranking
  llm.py         local Ollama candidate chooser
  models.py      shared extraction data models
  mutate.py      fixture mutation generator
  packs.py       domain pack loading/defaults
  ranker.py      tiny offline candidate ranker
  render.py      requests + optional Playwright rendering
  selectors.py   CSS selector generation
  snapshot.py    rendered-page snapshot capture
  spec.py        YAML spec loader
  validators.py  type-specific scalar validators

examples/
  product.yml
  product_v1.html
  product_v2.html
  article.yml
  article_v1.html

corpus/
  base_train/
  base_dev/
  base_holdout/
  adversarial_holdout/
  ood_dev/
  ood_holdout/
  repro_minimized/

packs/
  ecommerce/

tests/
  test_candidate_generation.py
  test_dataset_ranker.py
  test_evidence_store.py
  test_eval_model.py
  test_extract_no_llm.py
  test_pilot_pack.py
  test_selectors.py
  test_validators.py

fixtures/
  product/simple_card/
  article/news_article/
  listings/search_results/
  tables/pricing_table/
```

## Milestone Status

Detailed milestone notes live in [MILESTONES.md](MILESTONES.md). Current summary:

```text
M1-M5: complete
  static extraction, robustness harness, local model evaluation,
  selector cache, confidence gates, and calibrated safe-local policy

M6-M6E: complete
  rendered snapshots, canary/replay corpus, failure triage,
  selector memory hardening, and cross-version drift validation

M7A-M7C: complete
  tiny offline ranker, ranker safety calibration, and LLM fallback-call reduction

M8A/M8C/M8B: complete
  OOD canary suite, OOD hardening, and developer alpha packaging

M9-M12: complete
  structural evidence store, evidence-driven base ranker expansion,
  opt-in evidence bundles/intake, and domain-pack release loop

M13-M15R: complete through remediation
  external-style field trials repeatedly found false positives,
  which were converted into targeted gates, hard negatives, and regression suites

M16: tooling/docs complete
M16F: measurement integrity fix complete
M16C local stand-in cohort: passed safety
M16R-Founder: founder external safety remediation passed
M16U: safe coverage recovery passed
M16W: founder-operated wide external corpus failed safety/recall
M16C true outside-user cohort: pending
```

Current frozen external-cohort target:

```text
v0.1.0-alpha.8
```

Do not mark M16C complete until outside users/projects run the frozen target, produce audited features-only bundles, and pass the cohort gate:

```text
10+ outside projects/users
5+ domains
60+ attempted fields
bundle_audit_pass_rate = 100%
aggregate false_positive_rate <= 2%
candidate_recall@40 >= 95%
ranker-local-safe coverage >= 55%
```

The next milestone after a passing outside cohort is M17: use true cohort evidence to build a public-alpha pack/ranker update candidate, then release-check it against accumulated regression and adversarial suites.

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
- Hosted dashboards, billing, or team workflows.
- Automatic cloud upload.
- Automatic global model training from unverified user runs.
- Neural fine-tuned local model.
- Full visual-layout model beyond the current rendered metadata and region features.

Those are later product layers. The current proof point is narrower: a local-first extractor with a conservative ranker, validation gates, abstention, and privacy-safe evidence loops.
