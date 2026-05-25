# semscrape milestones

## M1: Static HTML semantic extraction

**Question:** Can we find fields by meaning rather than fixed selectors?

Deliverables:

- YAML field specs.
- DOM candidate generation.
- Deterministic candidate ranker.
- Validators.
- CLI extraction.
- Unit tests.

Exit criteria:

- Product and article examples pass without LLM.
- Extraction returns scalar values, selectors, source, confidence, and validation details.

Status: complete.

## M2: Drift robustness harness

**Question:** Does the correct element remain in the candidate set after realistic structural changes?

Deliverables:

- HTML mutation tool.
- Recall@K command.
- Benchmark command.
- Distractor injection.

Exit criteria:

- Candidate recall@40 is high across mutated fixtures.
- Deterministic extraction succeeds on first mutation corpus.

Status: complete.

## M3: Local LLM selector repair

**Question:** Can a small local model choose the correct candidate when heuristics are uncertain?

Deliverables:

- Ollama client.
- JSON schema response format.
- Confidence threshold.
- Validation fallback.
- `eval-model` bakeoff command.
- Per-field JSONL rows.
- Failure corpus artifacts.
- Hard fixture corpus with distractors, changed layouts, missing fields, articles, listings, and tables.

Exit criteria:

- qwen3:1.7b or similar small model achieves acceptable choice accuracy on candidate lists.
- Failed model choices are logged into a failure corpus.

Acceptance gates:

- candidate_recall@40 >= 95%.
- model_choice_accuracy_when_candidate_present >= 90%.
- validated_accuracy >= 90%.
- false_positive_rate <= 2%.
- Abstention on ambiguous or missing fields is allowed.

Status: evaluation harness complete; local model bakeoff still needs to run against Ollama.

## M4: Persistent extraction memory

**Question:** Can repaired selectors be reused safely?

Deliverables:

- Selector lock/cache file.
- Cache-first extraction.
- Validation-before-trust.
- Repair fallback.

Exit criteria:

- `--learn` creates lock files.
- Broken cached selectors do not silently produce bad values.

Status: complete.

## M4B: Confidence gating and abstention

**Question:** Can semscrape avoid silently wrong extractions by abstaining when evidence is weak or ambiguous?

Deliverables:

- Validator reasons, penalties, and hard disqualifiers.
- Field-specific negative evidence for price, rating, article date, and title fields.
- Strict decision gate.
- `--strict`, `--min-confidence`, `--min-margin`, and `--min-validator-confidence` CLI flags.
- Eval summary metrics for coverage, misses, abstentions, ambiguous abstentions, model errors, and false positives.
- Tests for ambiguous candidates, missing fields, and near-miss scalar values.

Exit criteria:

- Heuristic strict candidate_recall@40 remains >= 95%.
- Heuristic strict false_positive_rate <= 5%.
- Every abstention/failure has a reason code.
- Model errors never crash eval runs.

Status: complete; local LLM strict comparison still needs Ollama.

## M5: Local model bakeoff and threshold calibration

**Question:** Can a local model recover coverage from strict-mode abstentions without reintroducing false positives?

Deliverables:

- `eval-model --strict` local model bakeoff for qwen3:1.7b, gemma3:1b, and qwen3:4b.
- `calibrate` command for confidence/margin/validator threshold sweeps.
- `calibrate --from-jsonl` mode so threshold sweeps can reuse model calls.
- `report` command for Markdown summaries of eval and calibration JSONL.

Exit criteria:

- Good: coverage >= 45% with false_positive_rate <= 2%.
- Great: coverage >= 60% with false_positive_rate <= 2%.
- Excellent: coverage >= 70% with false_positive_rate <= 2%.

Status: calibration/report tooling complete; first local bakeoff complete. qwen3:1.7b is the only promising model from the initial matrix.

## M5C: Safe local extraction policy

**Question:** Can semscrape run deterministically when confidence is high, call a local model only when needed, and abstain instead of guessing?

Deliverables:

- `--policy safe-local`.
- Conservative strict heuristic first.
- qwen3:1.7b model recovery only after heuristic abstention.
- Extraction trace output.
- Recovery metrics in eval/report output.
- Selector learning only after accepted decisions.
- Mocked locator tests for safe runtime behavior.

Exit criteria:

- safe-local coverage >= 60%.
- safe-local false_positive_rate <= 2%.
- model_call_rate < 75%.
- model errors never crash extraction.
- no selector is learned from an abstained or invalid result.

Status: complete on the fixture corpus.

Latest fixture result:

```text
coverage_rate: 0.606557
false_positive_rate: 0.000000
heuristic_accept_rate: 0.295082
heuristic_abstention_rate: 0.704918
model_call_rate: 0.704918
model_recovery_rate: 0.441860
model_error_rate: 0.032787
```

## M6: Rendered pages

**Question:** Can we run this against modern JavaScript pages?

Deliverables:

- Playwright rendering.
- `--render` and `--wait-for` flags.
- DOM snapshot extraction.

Exit criteria:

- The CLI can render and extract from client-side pages.
- The browser dependency remains optional.

Status: first pass complete.

## M6B: Real-world rendered-page canary corpus

**Question:** Can safe-local extraction survive real rendered browser DOMs while preserving low false positives?

Deliverables:

- `snapshot` command for rendered HTML, static HTML, screenshot, metadata, candidates, extraction output, and accessibility tree capture.
- Rendered candidate enrichment: visibility, bounding boxes, computed styles, viewport presence, z-index, and accessibility role/name hints.
- `canary` command for replayable real-page evaluation from stored `rendered.html` captures or live URLs.
- Failure artifacts for render failures, candidate misses, validator rejects, model abstentions, and model errors.
- First 15-30 page real corpus across product, article, listing, pricing, and docs pages.

Exit criteria:

- candidate_recall@40 >= 90% on the real corpus.
- safe-local coverage >= 50% on the first real corpus.
- false_positive_rate <= 2%.
- model_call_rate <= 80%.
- render_failure_rate <= 10%.
- selector_reuse_rate >= 40% on a second run.
- every failed extraction has a replayable artifact.

Status: infrastructure implemented; real-page corpus collection pending.

## M6C: Real canary corpus and failure triage

**Question:** Does safe-local still work on messy replayed DOM snapshots, and what is the next bottleneck?

Deliverables:

- Canary manifest format for grouped replay cases with IDs, categories, specs, and local replay inputs.
- Replay-first canary behavior; live rendering requires an explicit `--live` flag.
- Failure summarizer for canary/eval JSONL output and `*.result.json` failure artifacts.
- Selector reuse metrics: cache attempts, hit rate, validated hits, rejections, learned selector count, and model calls avoided.
- Rendered/visibility metrics: hidden-candidate rejection and visible-candidate acceptance rates.
- Repo-safe minimized replay corpus across product, article, listing, pricing, and docs/reference pages.

Exit criteria:

- First replay corpus report generated.
- false_positive_rate <= 2%.
- every failed extraction has a reason code from the failure taxonomy.
- replayed snapshots are deterministic.
- second pass shows measurable selector reuse when a cache from the learn pass is reused.

Status: implemented for the minimized replay corpus; real third-party page captures should stay local under `corpus/real_local/` unless reduced to repo-safe repro cases.

## M6D: Selector memory hardening

**Question:** Can learned selectors generalize enough to reduce model calls without increasing false positives?

Deliverables:

- Multi-selector cache per field with structured selector records.
- Selector strategy labels and quality scoring.
- Cache validation/rejection reason codes.
- Selector strategy breakdown in canary/report output.
- Pass-to-pass replay comparison.
- Strict current cache format; malformed selector entries fail instead of being migrated.

Exit criteria:

- candidate_recall@40 >= 95%.
- safe-local coverage >= 60%.
- false_positive_rate <= 2%.
- selector_reuse_rate >= 40%.
- model_call_rate <= 60%.
- cache_false_positive_rate = 0%.
- every rejected cached selector has a reason code.

Status: complete on the minimized replay corpus.

Latest minimized replay result:

```text
pass1:
  coverage_rate: 0.700000
  false_positive_rate: 0.000000
  model_call_rate: 0.600000

pass2:
  candidate_recall_at_k: 0.985507
  coverage_rate: 0.700000
  false_positive_rate: 0.000000
  selector_reuse_rate: 0.700000
  model_call_rate: 0.300000
  cache_false_positive_rate: 0.000000
```

## M6E: Selector memory generalization under drift

**Question:** Do learned selectors survive realistic DOM changes, or only exact replay?

Deliverables:

- Versioned corpus manifests with group/version metadata.
- Drift generation for rendered snapshots.
- Cross-version canary comparison.
- Strategy-level reuse and rejection report.
- Cache schema versioning.
- Failure artifacts for cross-version selector misses and stale selectors.
- Relative memory strategies for headings, organic result regions, and tables.

Exit criteria:

- cross_version_candidate_recall@40 >= 95%.
- cross_version_coverage >= 65%.
- cross_version_false_positive_rate <= 2%.
- cross_version_selector_reuse_rate >= 45%.
- cross_version_model_call_rate <= 50%.
- cache_false_positive_rate = 0%.

Status: complete on the minimized cross-version replay corpus.

Latest cross-version replay result:

```text
learn-v1:
  coverage_rate: 0.944444
  false_positive_rate: 0.000000
  model_call_rate: 0.444444

test-v2:
  cross_version_candidate_recall_at_40: 0.980392
  cross_version_coverage: 0.846154
  cross_version_false_positive_rate: 0.000000
  cross_version_selector_reuse_rate: 0.500000
  cross_version_model_call_rate: 0.346154
  cache_false_positive_rate: 0.000000
```

## M7: Specialized local ranker

**Question:** Is a tiny specialized model better than generic local LLMs for this task?

Deliverables:

- Labeled candidate dataset.
- Model comparison harness.
- Pairwise ranker or token classifier.
- Optional ONNX/gguf artifact.

Exit criteria:

- Smaller/faster than generic LLM.
- Equal or better candidate-choice accuracy.
- Works fully offline.

Status: not started.

## M7A: Tiny candidate ranker

**Question:** Can a lightweight offline ranker replace most qwen3:1.7b recovery calls while preserving low false positives?

Deliverables:

- Candidate-ranking dataset builder: `semscrape dataset build`.
- Group-aware train/test split: `semscrape dataset split`.
- Hard-negative features for near-miss values such as shipping prices, list prices, sponsored titles, hidden duplicates, and wrong table cells.
- Tiny centroid-delta ranker: `semscrape ranker train`.
- Ranker evaluation and calibration: `semscrape ranker eval` and `semscrape ranker calibrate`.
- Runtime policies: `ranker-local` and `ranker-plus-llm`.
- Ranker metrics in eval/canary summaries.

Exit criteria:

- ranker-local coverage >= 70%.
- ranker-local false_positive_rate <= 2%.
- ranker-local model_call_rate = 0%.
- ranker-local p95 latency <= 50 ms/field.
- ranker-plus-llm coverage >= M6E safe-local coverage.
- ranker-plus-llm qwen3:1.7b call rate <= 15%.
- cache_false_positive_rate = 0%.

Status: implemented, not passed. Initial canary exposed unsafe `ranker-local` false positives.

## M7B: Ranker calibration and safety gates

**Question:** Can the offline ranker recover coverage without silently accepting near-miss candidates?

Deliverables:

- Hard-negative weighted centroid training.
- Ranker decision gate with explicit reason codes:
  - `low_ranker_confidence`
  - `low_ranker_margin`
  - `ranker_hidden_candidate`
  - `ranker_validator_disqualified`
  - `ranker_validator_rejected`
  - `low_validator_confidence`
  - `ranker_penalty_limit`
  - field-aware gates for titles, summaries, authors, coupons, dates, and monthly-vs-annual prices.
- Calibration sweep over ranker confidence, ranker margin, validator confidence, and max penalty count.
- `--target-fpr` alias for ranker calibration.
- Ranker false-positive diagnostics in reports.
- `ranker-plus-llm` only falls back to the LLM after safe ranker abstentions; unsafe ranker choices return abstention.

Current minimized drift result:

```text
ranker-local:
  coverage_rate:       0.769231
  false_positive_rate: 0.000000
  model_call_rate:     0.000000
  ranker_latency_p95:  2.0 ms

ranker-plus-llm qwen3:1.7b:
  coverage_rate:       0.846154
  false_positive_rate: 0.000000
  model_call_rate:     0.211538
  model_latency_p95:   16861.0 ms
```

Exit criteria:

- ranker-local coverage >= 65%.
- ranker-local false_positive_rate <= 2%.
- ranker-local model_call_rate = 0%.
- ranker-local p95 latency <= 50 ms/field.
- ranker-plus-llm false_positive_rate <= 2%.
- ranker-plus-llm coverage >= M6E safe-local coverage.
- ranker-plus-llm qwen3:1.7b call rate <= 15%.

Status: ranker-local gate passed. Live `ranker-plus-llm` with `qwen3:1.7b` improved coverage with zero false positives, but missed the qwen call-rate target before fallback gating.

## M7C: Fallback-call reduction

**Question:** Can the hybrid ranker + qwen path keep coverage while suppressing unproductive local LLM calls?

Deliverables:

- `--llm-fallback-policy all|recoverable-only|budgeted`.
- Default `ranker-plus-llm` fallback policy: `recoverable-only`.
- Pre-LLM recoverability gate based on strict-eligible visible candidates and field-specific absent-coupon suppression.
- `semscrape fallback audit` for productive, suppressed, abstained, and rejected qwen calls.
- LLM fallback metrics in eval/canary/report summaries.
- Tests proving recoverable-only suppresses unproductive qwen calls and `all` preserves the previous behavior.

Current minimized drift result:

```text
ranker-plus-llm qwen3:1.7b recoverable-only:
  coverage_rate:       0.846154
  false_positive_rate: 0.000000
  model_call_rate:     0.076923
  fallback_yield:      1.000000
  suppressed_calls:    7
```

Exit criteria:

- ranker-local coverage >= 75%.
- ranker-local false_positive_rate <= 2%.
- ranker-local model_call_rate = 0%.
- ranker-plus-llm coverage >= 0.846154, or >= 0.82 if exact coverage cannot hold.
- ranker-plus-llm false_positive_rate <= 2%.
- ranker-plus-llm qwen3:1.7b call rate <= 15%.
- qwen fallback yield >= 55%.

Status: passed on minimized drift canary.

## M8A: Out-of-distribution canary suite

**Question:** Does semscrape remain safe on unseen templates and adversarial drift?

Deliverables:

- `corpus/ood/manifest.yml` with in-domain holdout, near-domain, far-domain, and adversarial buckets.
- Replay-only OOD cases with committed `spec.yml` and `rendered.html` files.
- Bucket metadata in canary rows.
- Field type metadata in canary rows.
- `semscrape report-domain` for bucketed domain-envelope reports.
- Narrow safety gates for non-first organic result candidates, availability-price confusion, and ad-region fallback suppression.

Current OOD canary result:

```text
ranker-local:
  coverage_rate:       0.666667
  false_positive_rate: 0.000000
  model_call_rate:     0.000000

ranker-plus-llm qwen3:1.7b:
  coverage_rate:       0.703704
  false_positive_rate: 0.000000
  model_call_rate:     0.074074
```

Domain-envelope highlights:

```text
in_domain_holdout ranker-local coverage: 0.857
near_domain ranker-local coverage:      0.818
far_domain ranker-local coverage:       1.000
adversarial false_positive_rate:        0.000
```

Exit criteria:

- in-domain holdout ranker-local coverage >= 75%.
- near-domain ranker-local coverage >= 60%.
- all buckets false_positive_rate <= 2%.
- adversarial false_positive_rate = 0%.
- hybrid improves coverage over ranker-local without exceeding 15% qwen call rate.

Status: passed on initial OOD canary corpus.

## M8C: OOD hardening pass

**Question:** Can we improve OOD coverage without increasing false positives?

Deliverables:

- `corpus/ood_dev/manifest.yml` for development hardening and ranker-v2 training.
- `corpus/ood_holdout/manifest.yml` for a sealed replay holdout that is not used for training.
- Expanded holdout replay cases across product, article, docs, pricing, recipe, job, and adversarial traps.
- `models/candidate-ranker-v2.json`, trained from minimized drift plus OOD dev rows only.
- Targeted safety gates for:
  - product prices whose specs mention excluded coupon savings;
  - monthly prices near annual prices;
  - author section/category labels;
  - titles inside sponsored, recommended, or related regions;
  - qwen fallback on ad-region and monthly-vs-annual price traps.
- Calibrated ranker-local canary run with `--max-ranker-penalties 1`.

Current calibrated OOD result:

```text
OOD dev ranker-local:
  coverage_rate:       0.777778
  false_positive_rate: 0.000000
  model_call_rate:     0.000000

OOD holdout ranker-local:
  coverage_rate:       0.730769
  false_positive_rate: 0.000000
  model_call_rate:     0.000000

OOD holdout ranker-plus-llm qwen3:1.7b:
  coverage_rate:       0.730769
  false_positive_rate: 0.000000
  model_call_rate:     0.000000
```

Notes:

- The v2 ranker clears the OOD dev and sealed holdout ranker-local coverage/safety gates under the calibrated penalty setting.
- The hybrid path is safe on this sealed holdout, but it does not improve coverage because the recoverability gate suppresses all candidate sets as ad-region, monthly-vs-annual, or not strictly eligible.
- The next OOD suite should include positive fallback-recoverable holdout cases if hybrid coverage lift remains a release criterion.

Exit criteria:

- OOD dev ranker-local coverage >= 75%.
- OOD dev false_positive_rate = 0%.
- OOD holdout ranker-local coverage >= 65%.
- OOD holdout false_positive_rate <= 2%.
- Adversarial false_positive_rate = 0%.
- Hybrid improves holdout coverage with qwen_call_rate <= 10%.

Status: ranker-local gate passed on OOD dev and sealed holdout; hybrid safety passed, but hybrid coverage lift is pending.

## M8B: Developer alpha packaging

**Question:** Can another developer install semscrape and use it safely as a CLI tool?

Deliverables:

- Packaged default ranker artifact. M8B shipped `candidate-ranker-v2`; M10 promoted `candidate-ranker-v3`.
- `ranker-local` works without explicit `--ranker`.
- `semscrape ranker info`.
- `semscrape doctor`.
- `semscrape init`.
- Required-field flags:
  - `--require-fields`
  - `--fail-on-abstain`
  - `--min-coverage`
- Deterministic alpha exit codes.
- GitHub Actions CI for ruff, pytest, doctor, ranker info, offline extract, and OOD holdout canary smoke.
- Alpha quickstart docs.
- Versioned ranker artifact metadata and release checklist.

Exit criteria:

- Fresh clone can run tests and demos.
- Offline ranker-local demo works without Ollama.
- OOD holdout canary works without Ollama.
- Required-field workflows return deterministic exit codes.
- Optional qwen fallback is documented but not required.

Status: passed for developer-alpha packaging.

## M9: Structural Evidence Store and Learning Loop

**Question:** Can semscrape turn extraction attempts, failures, abstentions, canaries, and user corrections into trustworthy training/evaluation evidence?

Deliverables:

- Local SQLite evidence store at `.semscrape/evidence.db` by default.
- `--record-evidence`, `--evidence-db`, and `--evidence-privacy` for `extract`, `canary`, and policy eval flows.
- EvidenceRecord v1 fields for run metadata, spec/input hashes, field identity, candidates, selection source, validator state, ranker state, trace, failure reason, label state, and trust level.
- Automatic gold labels from benchmark/canary expected values.
- Manual correction commands:
  - `semscrape evidence label DB RECORD_ID --correct-candidate CANDIDATE_ID`
  - `semscrape evidence label DB RECORD_ID --correct-value VALUE`
  - `semscrape evidence label DB RECORD_ID --abstention-correct`
- Evidence inspection commands:
  - `semscrape evidence stats`
  - `semscrape evidence review`
  - `semscrape evidence export`
- Privacy modes:
  - `full`
  - `redacted`
  - `features-only`
- Evidence-derived ranker data:
  - `semscrape dataset build --from-evidence`
- Ranker model-card generation:
  - `semscrape ranker model-card`

Exit criteria:

- Evidence capture works for `extract` and `canary` ranker-local workflows.
- Benchmark/canary expected values become gold labels.
- User corrections can label correct candidates, corrected values, or correct abstentions.
- Features-only export strips raw candidate values, full candidate text, full candidate context, and selectors.
- Dataset build can consume evidence exports.
- Existing M8B alpha CLI workflows still pass.

Status: implemented; M10 now uses the evidence/corpus workflow to train and gate ranker release candidates.

## M10: Base Ranker Expansion and Release Candidate

**Question:** Can we train a broader base ranker from trusted structural evidence and prove it on sealed holdouts without increasing false positives?

Deliverables:

- Structured M10 corpus manifests:
  - `corpus/base_train/manifest.yml`
  - `corpus/base_dev/manifest.yml`
  - `corpus/base_holdout/manifest.yml`
  - `corpus/adversarial_holdout/manifest.yml`
- Sealed-corpus rules documented in `corpus/README.md`.
- Safer hard-negative feature matching so short trap terms like `ad` do not match substrings such as `heading`.
- Additional ranker gate for storage candidates in related/recommended/archive regions.
- Candidate-ranker-v3 trained from base train/dev cases.
- Candidate-ranker-v3 model card with training-data and sealed-eval summaries.
- `semscrape ranker release-check` for promotion gates.
- Packaged default ranker promoted to `candidate-ranker-v3`.

Release-candidate result:

```text
base_holdout candidate_recall@40: 1.000000
base_holdout ranker-local coverage: 1.000000
base_holdout false_positive_rate: 0.000000
base_holdout model_call_rate: 0.000000
adversarial_holdout false_positive_rate: 0.000000
release_check: passed
```

Exit criteria:

- base holdout candidate_recall@40 >= 95%.
- base holdout ranker-local coverage >= 75%.
- base holdout false_positive_rate <= 2%.
- adversarial holdout false_positive_rate = 0%.
- v3 does not regress v2 false-positive safety.
- unverified production outputs are excluded from positive training labels.
- if v3 passes, package it as default; otherwise keep v2.

Status: passed for the initial replay release-candidate suite. The corpus is still intentionally small, so the model card treats the domain envelope as replay-validated rather than universal web robustness.

## M11: Opt-in Evidence Contribution and Ranker Update Pipeline

**Question:** Can semscrape safely turn real-world usage evidence into future ranker/domain-pack improvements without leaking private data or poisoning the model?

Deliverables:

- `semscrape evidence bundle` for reviewable opt-in evidence archives.
- Bundle contents:
  - `manifest.json`
  - `records.jsonl`
  - `schema.json`
  - `privacy_report.json`
  - `summary.json`
- `semscrape evidence audit` for privacy and schema checks.
- Trust-level export enforcement:
  - `gold`
  - `silver`
  - `bronze`
  - `untrusted`
- `semscrape evidence export --min-trust`, defaulting to `silver` for training-oriented exports.
- Batch review workflow:
  - `semscrape evidence review --write-review-file`
  - `semscrape evidence apply-review`
- Maintainer-side `semscrape evidence intake` with bundle validation and deduplication.
- Domain-pack skeleton:
  - `packs/ecommerce/pack.yml`
  - pack thresholds, validator notes, supported fields, and model card.
- `--pack ecommerce` support for extraction, benchmark, eval, snapshot, and canary commands.

M11 smoke result:

```text
ecommerce pack extract: passed
features-only bundle: 4 records, 4 gold labels
privacy audit: passed
intake: 4 records accepted, 0 duplicates
dataset build from intake: 92 candidate rows, 5 positives, 20 hard negatives
```

Exit criteria:

- Features-only bundles contain no raw HTML or full candidate text.
- Training exports exclude unverified production positives by default.
- User corrections become gold labels.
- Malformed/privacy-unsafe bundles are rejected.
- Maintainer intake validates bundles and summarizes trust levels.
- Domain-pack defaults can be used locally.
- Existing alpha CLI workflows still pass.

Status: passed. The contribution workflow remains local/offline; no cloud ingestion service is included.

## M12: Alpha Pilot + Domain Pack Release Loop

**Question:** Can real project usage produce privacy-safe evidence that improves a domain pack/ranker release without regressing false-positive safety?

Deliverables:

- Pilot project layout:
  - `pilots/ecommerce_alpha_001`
  - `pilots/articles_alpha_001`
  - `pilots/listings_alpha_001`
- `semscrape pilot run` for end-to-end local pilot execution.
- Pilot artifacts:
  - `runs/summary.json`
  - `runs/report.md`
  - `runs/domain-report.md`
  - local `evidence.db`
  - local `evidence-bundle.zip`
- Generated pilot evidence DBs, bundles, and run outputs are ignored by git.
- `semscrape pack build`.
- `semscrape pack info`.
- `semscrape pack release-check`.
- `semscrape pack compare`.
- Pack promotion guardrails for:
  - candidate recall
  - holdout coverage
  - holdout false-positive rate
  - no FPR regression versus baseline
  - adversarial false-positive rate
  - model-call rate
  - ranker schema compatibility
  - model-card presence
- First ecommerce pack release candidate:
  - `packs/ecommerce-v1`

M12 local pilot result:

```text
pilots run end-to-end: 3
pilot evidence records: 11
pilot labeled records: 11
bundle audit pass rate: 3/3
intake accepted records: 11
intake trust levels: 11 gold
```

M12 ecommerce-v1 release-check result:

```text
base holdout candidate_recall@40: 1.000000
base holdout baseline coverage:   1.000000
base holdout candidate coverage:  1.000000
candidate false_positive_rate:    0.000000
candidate model_call_rate:        0.000000
adversarial false_positive_rate:  0.000000
promotion: promote_candidate
```

Exit criteria:

- At least 3 pilot projects run end-to-end locally.
- Features-only evidence bundles pass privacy audit.
- Intake accepts valid bundles and rejects unsafe/tampered bundles.
- ecommerce-v1 improves or matches baseline holdout coverage.
- ecommerce-v1 false_positive_rate <= 2%.
- adversarial false_positive_rate = 0%.
- no unverified production outputs are used as positive training labels.

Status: passed for the local replay alpha-pilot loop. The pack release candidate is evidence-derived from local pilot bundles and release-checked against the current sealed replay holdouts.

## M13: External Alpha Field Trials

**Question:** Can semscrape work on real user/projects outside the curated repo corpus while preserving false-positive safety and generating useful pack/ranker evidence?

Deliverables:

- Alpha pilot playbook:
  - `docs/alpha_pilot_playbook.md`
- `semscrape pilot report`.
- `semscrape pilot summarize`.
- `semscrape pack gaps`.
- Pilot scorecard fields:
  - fields attempted
  - required-field success rate
  - coverage rate
  - false-positive rate
  - abstention rate
  - candidate recall
  - evidence record count
  - labeled record count
  - bundle audit result
  - correction count placeholder
- Aggregate pilot summary report.
- Pack gap analysis by field type, failure reason, hard-negative trap, validator rejection, and candidate-missing count.

M13 tooling smoke result on the existing local alpha pilots:

```text
pilots summarized: 3
domains represented: 3
fields summarized: 11
aggregate coverage_rate: 1.000000
aggregate false_positive_rate: 0.000000
bundle audit pass rate: 1.000000
pack gaps hard_negatives: 54
pack gaps candidate_missing: 0
```

Exit criteria for the actual external field-trial gate:

- 5+ pilots completed end to end.
- 3+ domains represented.
- aggregate false_positive_rate <= 2%.
- adversarial/manual trap false_positive_rate = 0%.
- ranker-local aggregate coverage >= 60%.
- every pilot bundle passes privacy audit.
- release-check blocks any candidate with false-positive regression.

M13C execution result against frozen `v0.1.0-alpha.1`:

```text
pilots: 5
domains: 4
fields: 15
coverage_rate: 1.000000
false_positive_rate: 0.333333
candidate_recall_at_40: 0.933333
bundle_audit_pass_rate: 1.000000
```

Status: tooling complete and external-style execution complete. The field-trial safety gate failed on correctness because unseen page semantics produced too many false positives. Evidence capture, privacy bundle audit, intake, and pilot reporting passed.

## M13R: External Alpha Safety Remediation

**Question:** Can we eliminate the false positives found in the first external alpha trial without overfitting or sacrificing the evidence loop?

Deliverables:

- False-positive incident report:
  - `docs/m13r_false_positive_incident_report.md`
- Targeted safety gates for:
  - published date vs updated/modified/revised date
  - page/site title vs tag-cloud/category headings
  - docs chapter prompts vs unrelated glossary/sidebar content
  - tag prompts vs byline/long-text candidates
  - author prompts vs CTA/navigation candidates
  - full availability messages vs generic stock statuses
- Heading-marker cleanup for Sphinx-style permalink markers.
- Tests covering the observed external-alpha traps.
- Original external-alpha remediation rerun.
- New mini-holdout pilot rerun.

Original external-alpha pilots after remediation:

```text
pilots: 5
domains: 4
fields: 15
coverage_rate: 0.933333
false_positive_rate: 0.000000
abstention_rate: 0.066667
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Mini-holdout pilots after remediation:

```text
pilots: 4
domains: 4
fields: 11
coverage_rate: 1.000000
false_positive_rate: 0.000000
abstention_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Exit criteria:

- Original external alpha false_positive_rate = 0.
- Original external alpha candidate_recall@40 >= 95%.
- New mini-holdout false_positive_rate <= 2%.
- New mini-holdout candidate_recall@40 >= 95%.
- Evidence/privacy flow remains intact.
- No unverified production positives are used for training.

Status: passed for the current external-alpha replay set and mini-holdout. No ranker artifact was promoted; M13R recovered safety through deterministic gates and validators while keeping pilot evidence local.

## M14: Alpha.2 Revalidation and Release Readiness

**Question:** Does the M13R-remediated alpha pass a fresh external-style field trial without regressing false-positive safety?

Deliverables:

- `v0.1.0-alpha.2` tag.
- Alpha.1 vs Alpha.2 remediation report:
  - `runs/m14/alpha1-vs-alpha2-remediation.md`
- Original external-alpha regression rerun.
- Fresh alpha.2 pilot run.
- Alpha.2 evidence intake and gap report.
- Release decision memo:
  - `runs/m14/release-decision.md`
- Validation summary:
  - `docs/m14_alpha2_validation_report.md`

Original external-alpha regression suite:

```text
pilots: 5
domains: 4
fields: 15
coverage_rate: 0.933333
false_positive_rate: 0.000000
abstention_rate: 0.066667
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Fresh alpha.2 pilots:

```text
pilots: 6
domains: 5
fields: 18
coverage_rate: 0.722223
false_positive_rate: 0.222222
abstention_rate: 0.277778
candidate_recall_at_40: 0.888889
bundle_audit_pass_rate: 1.000000
```

Holdout checks:

```text
base_holdout_coverage: 0.950000
base_holdout_false_positive_rate: 0.000000
adversarial_false_positive_rate: 0.000000
```

Evidence intake:

```text
records: 18
gold_labels: 18
positive_candidate_rows: 35
hard_negative_candidate_rows: 236
```

Exit criteria:

- Original external-alpha FPR = 0.
- Fresh alpha.2 pilot FPR <= 2%.
- Fresh alpha.2 candidate_recall@40 >= 95%.
- Fresh alpha.2 ranker-local coverage >= 60%.
- Base/adversarial holdouts remain FPR = 0.
- Every pilot bundle passes privacy audit.
- No unverified positives are used for model/ranker training.

Status: failed release-readiness. `v0.1.0-alpha.2` is a valid internal validation tag, but fresh alpha.2 pilots found new false positives and candidate-recall misses. Do not promote to public alpha before an M14R remediation pass.

## M14R: Fresh Alpha Safety Remediation

**Question:** Can we remediate the fresh alpha.2 false positives and recall misses without overfitting or sacrificing the evidence loop?

Deliverables:

- Fresh-alpha incident report:
  - `docs/m14r_fresh_alpha_incident_report.md`
- Targeted remediation for:
  - mojibake pound-symbol normalization during extraction and expected-value matching
  - first-listing title selection vs later listing-card titles
  - article/page titles vs section headings and price-shaped headings
  - docs section headings vs paragraphs and navigation/related/sidebar regions
  - plan-specific prices vs neighboring plan prices
  - ARIA `role="heading"` page-title candidates
- Fresh alpha.2 remediation rerun:
  - `runs/m14r/fresh-alpha2-remediation-summary.md`
- Final fresh mini-holdout rerun:
  - `runs/m14r/fresh-mini-holdout-summary.md`
- Base/adversarial regression reruns:
  - `runs/m14r/base-holdout-ranker-local.jsonl`
  - `runs/m14r/adversarial-holdout-ranker-local.jsonl`
- Release-check:
  - `runs/m14r/release-check.json`

Fresh alpha.2 remediation set:

```text
pilots: 6
domains: 5
fields: 18
coverage_rate: 0.777778
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Final fresh mini-holdout:

```text
pilots: 3
domains: 3
fields: 7
coverage_rate: 0.714286
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Base/adversarial regression:

```text
base_holdout:
  coverage_rate: 0.950000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

adversarial_holdout:
  false_positive_rate: 0.000000
```

Release-check:

```text
passed: true
promotion: promote_candidate
```

Exit criteria:

- Fresh alpha.2 remediation set FPR = 0.
- Fresh alpha.2 remediation set recall@40 >= 95%.
- Fresh mini-holdout FPR <= 2%.
- Fresh mini-holdout recall@40 >= 95%.
- Base/adversarial FPR remains 0.
- No unverified production positives are used for training.
- No new ranker artifact is promoted unless release-check passes.

Status: passed. M14R restored false-positive safety on the fresh alpha.2 remediation set, passed a separate final mini-holdout, preserved base/adversarial safety, and kept pilot artifacts local/ignored. The packaged ranker artifact remains `candidate-ranker-v3`; M14R changed deterministic gates and normalization only.

## M15: Alpha.3 Public-Alpha Readiness Trial

**Question:** Does the M14R-remediated build survive a larger fresh validation pass well enough to justify a public alpha release?

Deliverables:

- `v0.1.0-alpha.3` tag:
  - `2b92586a9d3478999c144f98c851cdb104d72dfc`
- Fresh alpha.3 pilot set:
  - `runs/m15/alpha3-summary.md`
- False-positive artifact:
  - `runs/m15/alpha3-false-positives.jsonl`
- Evidence intake and gap report:
  - local ignored artifact: `data/intake/alpha3-evidence.jsonl`
  - `runs/m15/alpha3-gaps.md`
- Regression reruns:
  - `runs/m15/original-external-alpha-regression-summary.md`
  - `runs/m15/m14-fresh-remediation-regression-summary.md`
  - `runs/m15/m14r-mini-holdout-regression-summary.md`
  - `runs/m15/base-holdout-ranker-local.jsonl`
  - `runs/m15/adversarial-holdout-ranker-local.jsonl`
- Public-readiness report:
  - `docs/m15_alpha3_public_readiness_report.md`

Fresh alpha.3 pilots:

```text
pilots: 11
domains: 6
fields: 31
coverage_rate: 0.741936
false_positive_rate: 0.096774
candidate_recall_at_40: 0.967742
bundle_audit_pass_rate: 1.000000
```

Regression suites:

```text
original_external_alpha:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

m14_fresh_remediation:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

m14r_mini_holdout:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

base_holdout:
  coverage_rate: 0.950000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

adversarial_holdout:
  false_positive_rate: 0.000000
```

Exit criteria:

- Fresh alpha.3 false_positive_rate <= 2%.
- Fresh alpha.3 candidate_recall@40 >= 95%.
- Fresh alpha.3 ranker-local coverage >= 60%.
- Every regression suite remains FPR = 0.
- Every features-only bundle passes audit.
- No unverified positives are used for training.

Status: failed public-alpha readiness. `v0.1.0-alpha.3` passed recall, coverage, bundle audit, and known-regression gates, but fresh alpha.3 false-positive rate was `0.096774`, above the `0.020000` gate. Do not promote to public alpha before M15R.

## M15R: Public-Alpha Safety Remediation

**Question:** Can we reduce fresh alpha.3 false positives below the public-alpha threshold without overfitting to the M15 pilot set?

Deliverables:

- M15 false-positive incident report:
  - `docs/m15r_public_alpha_incident_report.md`
- Public-alpha high-precision policy preset:
  - `ranker-local-safe`
- Field/region remediation for:
  - first repeated listing/product-card prices
  - recent h3/list item titles vs featured h1 titles
  - metadata definition-list values vs body/link/code candidates
  - docs section headings vs banners, hidden footer headings, footer columns, and sidebar-only regions
- Feature additions:
  - candidate before/after/parent text
  - region flags for toc, glossary, breadcrumb, metadata panel, and code regions
- M15 remediation rerun:
  - `runs/m15r/m15-remediation-summary.md`
- Fresh M15R mini-holdout rerun:
  - `runs/m15r/mini-holdout-summary.md`
- Accumulated regression reruns:
  - `runs/m15r/original-external-alpha-regression-summary.md`
  - `runs/m15r/m14-fresh-remediation-regression-summary.md`
  - `runs/m15r/m14r-mini-holdout-regression-summary.md`
- Base/adversarial reruns:
  - `runs/m15r/base-holdout-ranker-local-safe.jsonl`
  - `runs/m15r/adversarial-holdout-ranker-local-safe.jsonl`
- Release-check:
  - `runs/m15r/ranker-local-safe-release-check.json`
- Public-alpha safety report:
  - `docs/m15r_public_alpha_safety_report.md`

M15 remediation set:

```text
pilots: 11
domains: 6
fields: 31
coverage_rate: 0.709678
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Fresh M15R mini-holdout:

```text
pilots: 4
domains: 4
fields: 10
coverage_rate: 0.900000
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Regression suites:

```text
original_external_alpha:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

m14_fresh_remediation:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

m14r_mini_holdout:
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

base_holdout:
  coverage_rate: 0.950000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

adversarial_holdout:
  false_positive_rate: 0.000000
```

Release-check:

```text
passed: true
promotion: promote_candidate
```

Exit criteria:

- M15 remediation set FPR = 0.
- M15 remediation set recall@40 >= 95%.
- New M15R mini-holdout FPR <= 2%.
- New M15R mini-holdout recall@40 >= 95%.
- All regression suites remain FPR = 0.
- Base/adversarial FPR remains 0.
- Features-only bundle audits still pass.
- No unverified positives are used for training.
- `v0.1.0-alpha.4` is tagged only after the full gate passes.

Status: passed. M15R restored false-positive safety on the M15 fresh set, passed a separate mini-holdout, preserved all accumulated regression suites, and kept the release posture conservative through `ranker-local-safe`.

## M16: Controlled Public Alpha

**Question:** Can outside users install `v0.1.0-alpha.4`, use semscrape on their own workflows, and contribute privacy-safe evidence while preserving false-positive safety?

Deliverables:

- Public alpha release notes:
  - `CHANGELOG.md`
  - `docs/public_alpha.md`
  - `docs/known_limitations.md`
- Evidence intake runbook:
  - `docs/evidence_intake_runbook.md`
- GitHub issue templates:
  - false positive
  - unexpected abstention
  - candidate recall miss
  - spec help
  - pack/domain request
  - privacy/evidence bundle issue
- Alpha cohort summary command:
  - `semscrape alpha summarize alpha_bundles/*.zip --out runs/m16/public-alpha-summary.md`
- Controlled cohort:
  - 10+ alpha projects/users
  - 5+ domains
  - 60+ attempted fields

Exit criteria:

- `v0.1.0-alpha.4` public alpha notes exist.
- Known limitations are documented.
- Install/doctor/init/extract/evidence bundle workflow is documented.
- 10+ projects/users complete the workflow.
- 5+ domains are represented.
- 60+ fields are attempted.
- Features-only bundle audit pass rate = 100%.
- Aggregate false_positive_rate <= 2%.
- Candidate_recall@40 >= 95%.
- `ranker-local-safe` coverage >= 55%.
- All false positives become gold hard negatives.
- No unverified production positives are used for global training.

Status: tooling/docs ready, field-trial gate pending. `v0.1.0-alpha.5` is the frozen controlled public-alpha cohort target because it includes the M15R safety fixes plus M16 onboarding/tooling. `v0.1.0-alpha.4` remains the safety-remediation extraction tag.

## M16C: Controlled Public Alpha Execution

**Question:** Can outside users/projects use the frozen public-alpha build end to end, produce audited evidence bundles, and preserve false-positive safety?

Frozen target:

```text
v0.1.0-alpha.5
commit: f70905186976132db1764f91c784e19f1a40e40f
```

Deliverables:

- 10+ completed alpha projects/users.
- 5+ represented domains.
- 60+ attempted fields.
- Aggregate public-alpha summary:
  - `semscrape alpha summarize alpha_bundles/*.zip --out runs/m16/public-alpha-summary.md`
- Evidence intake:
  - `semscrape evidence intake alpha_bundles/*.zip --out data/intake/m16-public-alpha-evidence.jsonl`
- Pack/domain gap report:
  - `semscrape pack gaps data/intake/m16-public-alpha-evidence.jsonl --pack ecommerce --out runs/m16/public-alpha-gaps.md`
- Issue triage summary.

Exit criteria:

- 10+ projects/users complete the workflow.
- 5+ domains represented.
- 60+ attempted fields.
- Every project produces a report, evidence DB, features-only bundle, and privacy audit.
- Aggregate false_positive_rate <= 2%.
- Candidate_recall@40 >= 95%.
- `ranker-local-safe` coverage >= 55%.
- Bundle audit pass rate = 100%.
- Regression/adversarial suites remain FPR = 0.
- All false positives become gold hard negatives.
- No unverified production positives are used for global training.

Status: local stand-in cohort passed safety under corrected final-result metrics; true outside-user field gate pending. `v0.1.0-alpha.5` found a measurement bug where `alpha summarize` overcounted final abstentions with rejected trace candidates as false positives. Do not use `v0.1.0-alpha.5` for the true outside-user cohort.

## M16F: Measurement Integrity Fix

**Question:** Do alpha/cohort/reporting commands compute false positives, abstentions, coverage, and recall consistently with the final extraction result?

Deliverables:

- Final-result false-positive definition:
  - final `status = extracted`
  - labeled expected value/candidate exists or expected field is absent
  - selected value/candidate is wrong
- `semscrape alpha summarize` fixed so safe abstentions are not false positives.
- `semscrape pack gaps` fixed to use the same final-result false-positive definition.
- Evidence stats fixed to require final extracted status for false-positive counts.
- Regression tests for:
  - abstained row with rejected wrong trace candidate
  - extracted wrong row
  - extracted correct row
  - expected-absent extracted row
  - candidate recall denominator independent from final extraction status
- `v0.1.0-alpha.6` tag for the true outside-user cohort target.

Exit criteria:

- M16C local stand-in cohort corrected summary:
  - 25 bundles/projects
  - 6 domains
  - 69 attempted fields
  - coverage_rate = 0.753623
  - false_positive_rate = 0.000000
  - candidate_recall@40 = 1.000000
  - bundle_audit_pass_rate = 1.000000
- `python -m ruff check .` passes.
- `python -m pytest -q` passes.

Status: complete. `v0.1.0-alpha.6` is the frozen target for true outside-user M16C execution. `v0.1.0-alpha.5` remains a valid packaging tag but contains the alpha-summary measurement bug.

## M16R-Founder: Founder External Safety Remediation

**Question:** Can we remediate founder-operated external cohort failures before inviting true outside users?

Baseline alpha.6 founder-operated external cohort:

```text
bundles: 16
accepted_bundles: 15
domains: 5
fields_attempted: 75
coverage_rate: 0.986667
false_positive_rate: 0.333333
candidate_recall_at_40: 0.933333
bundle_audit_pass_rate: 0.937500
```

Failure families:

- features-only bundle privacy leak in candidate before/after text.
- repeated/list ordinal confusion.
- docs navigation/title context confusion.
- product/table row and column confusion.
- generic text overmatches.
- candidate recall misses from long leaf text, title attributes, documentation labels, and table percentage candidates.

Deliverables:

- Features-only bundle leak fix.
- Privacy audit regression tests for raw HTML and full candidate text.
- Founder external incident report:
  - `docs/m16r_founder_external_incident_report.md`
- Targeted safety gates for repeated/list contexts, docs title/navigation contexts, table fields, generic sentence fields, links, RFC values, and product metadata values.
- Candidate recall fixes for long text, title attributes, documentation labels, quote text, table percentage, and ordinal listing candidates.
- Timeout/operational failures kept separate from extraction correctness.
- Founder remediation rerun.
- Fresh mini-holdout rerun.
- Base/adversarial regression rerun.

Remediated founder external rerun:

```text
bundles: 18
domains: 6
fields_attempted: 91
coverage_rate: 0.296703
false_positive_rate: 0.000000
candidate_recall_at_40: 0.989011
abstention_rate: 0.703297
bundle_audit_pass_rate: 1.000000
```

One founder project timed out during the final rerun and is excluded from extraction correctness metrics.

Fresh M16R mini-holdout:

```text
bundles: 5
domains: 5
fields_attempted: 22
coverage_rate: 0.318182
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
abstention_rate: 0.681818
bundle_audit_pass_rate: 1.000000
```

Regression suites:

```text
base_holdout:
  rows: 20
  coverage_rate: 0.350000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

adversarial_holdout:
  rows: 6
  coverage_rate: 0.000000
  false_positive_rate: 0.000000
```

Exit criteria:

- Founder remediation FPR = 0.
- Founder remediation candidate_recall@40 >= 95%.
- Founder remediation bundle audit pass rate = 100%.
- Fresh mini-holdout FPR <= 2%.
- Fresh mini-holdout candidate_recall@40 >= 95%.
- Base/adversarial FPR remains 0.
- No unverified positives are used for training.

Status: passed. `v0.1.0-alpha.7` is the safety-remediated founder external cohort tag. Coverage is intentionally conservative; true outside-user M16C remains pending.

## M16U: Safe Coverage Recovery

**Question:** Can we recover useful public-alpha coverage after M16R-Founder without reintroducing false positives or privacy risk?

M16R-Founder fixed safety and privacy, but made `ranker-local-safe` too quiet for outside-user alpha validation:

```text
founder_external_remediation:
  coverage_rate:          0.296703
  false_positive_rate:    0.000000
  candidate_recall@40:    0.989011
  bundle_audit_pass_rate: 1.000000

fresh_mini_holdout:
  coverage_rate:          0.318182
  false_positive_rate:    0.000000
  candidate_recall@40:    1.000000
  bundle_audit_pass_rate: 1.000000
```

Deliverables:

- Safe acceptance ladder for low-margin ranker choices that have strong structural evidence.
- Recoverable-vs-unsafe abstention split:
  - recover structured candidates in safe regions with strong validator evidence
  - keep abstaining on known trap regions, candidate misses, ambiguous docs/list/table contexts, and weak generic text
- Narrow fixes for:
  - quote/card ordinals
  - RFC ordinal anchors
  - truncated product titles
  - Python tutorial navigation links vs module index links
  - quote text fields vs quote-page title fields
- Refreshed founder and fresh mini-holdout evidence bundles.
- Regression checks against base and adversarial holdouts.
- Report:
  - `docs/m16u_safe_coverage_recovery_report.md`

Founder-operated external remediation set after M16U:

```text
bundles:                18
fields_attempted:       91
coverage_rate:          0.769231
false_positive_rate:    0.000000
candidate_recall@40:    0.989011
abstention_rate:        0.230769
bundle_audit_pass_rate: 1.000000
```

Fresh M16R mini-holdout after M16U:

```text
bundles:                6
fields_attempted:       27
domains:                5
coverage_rate:          0.555556
false_positive_rate:    0.000000
candidate_recall@40:    0.962963
abstention_rate:        0.444444
bundle_audit_pass_rate: 1.000000
```

Regression:

```text
base_holdout:
  fields_attempted:     20
  coverage_rate:        0.450000
  false_positive_rate:  0.000000
  candidate_recall@40:  1.000000

adversarial_holdout:
  fields_attempted:     6
  coverage_rate:        0.000000
  false_positive_rate:  0.000000
```

Status: passed. M16C true outside-user execution remains pending. `v0.1.0-alpha.8` is the intended frozen outside-user cohort target because `v0.1.0-alpha.7` is safe but over-abstains.

## M16W: Founder-Operated Wide External Corpus

**Question:** Can `v0.1.0-alpha.8` maintain low false positives across a much wider set of fresh public pages when operated by the founder under a frozen protocol?

Status: executed, failed safety/recall gate.

This is not a true outside-user cohort. It tests content/page generalization under founder operation, not independent-user onboarding, spec writing, or workflow comprehension.

Completed corpus:

```text
projects_completed:     54
fields_attempted:       267
domains/source groups:  14
bundle_audit_pass_rate: 1.000000
```

Results:

```text
coverage_rate:          0.629213
false_positive_rate:    0.026217
false_positives:        7
candidate_recall@40:    0.850187
candidate_missing:      40
abstention_rate:        0.370787
bundle_audit_pass_rate: 1.000000
```

Gate result:

```text
50+ projects/pages:                pass
8+ domains/source groups:          pass
200+ attempted fields:             pass
bundle audit pass rate = 100%:     pass
ranker-local-safe coverage >= 50%: pass
false_positive_rate <= 2%:         fail
candidate_recall@40 >= 95%:        fail
```

M16W also found a measurement bug: `alpha summarize` and `pack gaps` undercounted extracted-wrong rows when `candidate_recall=false` and no positive candidate row existed in a features-only evidence export. The metric now counts those rows as false positives, matching the M16F final-result definition.

Report:

- `docs/m16w_founder_wide_report.md`

Decision: true outside-user M16C remains blocked. Next milestone should be M16W-R: improve candidate recall for metadata/paragraph/main-content candidates and prevent extraction when the expected candidate is missing, then rerun the founder-wide set plus a fresh wide mini-holdout.

## M16W-R: Wide Corpus Recall and Missing-Candidate Safety

Status: passed.

Question: Can semscrape improve candidate recall on the wide external corpus and abstain safely when the requested field is not represented strongly in the candidate set?

Changes:

```text
- Included value-bearing metadata candidates from <meta content=...>.
- Used metadata/attribute text as candidate text for non-visible value-bearing elements.
- Replaced expensive per-candidate unique-selector probing with deterministic sibling-aware structural selectors.
- Added meta-description safety gates.
- Added first-section ordinal annotation/gating.
- Added first-content-link ordinal gating.
- Added repeated-card ordinal safety for quote/product/listing fields.
- Added document-title gating so SVG title elements cannot satisfy HTML document title fields.
- Added paragraph-specific ranking for first_paragraph-like prompts.
- Classified and removed invalid generated expected-value rows from the founder-wide remediation measurement set.
```

Incident reports:

```text
docs/m16w_r_candidate_recall_incident_report.md
docs/m16w_r_false_positive_incident_report.md
```

Founder-wide remediation result:

```text
projects/pages:         60
source groups:          14
fields_attempted:       257
coverage_rate:          0.692607
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
abstention_rate:        0.307393
bundle_audit_pass_rate: 1.000000
```

Fresh wide mini-holdout result:

```text
projects/pages:         16
source groups:          7
fields_attempted:       61
coverage_rate:          0.721311
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
abstention_rate:        0.278689
bundle_audit_pass_rate: 1.000000
```

Regression:

```text
base_holdout_false_positive_rate:        0.000000
adversarial_holdout_false_positive_rate: 0.000000
```

Decision:

```text
M16W-R passed.
v0.1.0-alpha.9 is the next frozen outside-user cohort target after this commit is tagged.
M16C true outside-user cohort can resume on v0.1.0-alpha.9 unless a blocking runtime bug appears.
```

## M17: Automated External Evidence Harvester

Status: tooling implemented; 100+ source evidence gate pending.

Question: Can semscrape continuously collect privacy-safe evidence from fresh public sources, prioritize useful review items, and feed trusted labels into the ranker/pack loop without poisoning the model?

Deliverables implemented:

```text
- `sources/external.yml` source registry.
- `semscrape alpha run sources/external.yml`.
- Split metadata: dev, holdout, adversarial, monitor_only, train_candidate.
- Expected-mode and label-policy metadata.
- Per-source canary/evidence capture.
- Features-only bundle creation and audit.
- Automatic intake JSONL.
- Automatic alpha summary and pack gap report.
- Review queue for false positives, candidate misses, recoverable abstentions, low-margin accepts, risky accepts, and unverified extractions.
- Scheduled local runner: scripts/run_alpha_harvester.ps1.
- Documentation: docs/automated_evidence_harvester.md.
```

Safety rule:

```text
continuous evidence collection: yes
automatic positive labeling from raw outputs: no
automatic model/pack promotion: no
```

Smoke result:

```text
command: semscrape alpha run sources/external.yml --out runs/m17/smoke --force --no-respect-rate-limits --pack ecommerce
sources:                  2
bundles:                  2
fields_attempted:         8
bundle_audit_pass_rate:   1.000000
false_positive_rate:      0.000000
candidate_recall@40:      1.000000
review_queue_items:       4
```

Remaining gate:

```text
- 100+ source runs complete with bundle_audit_pass_rate = 100%.
- No unverified extraction is exported as a positive training label.
- Review queue ranks high-value examples.
- Holdout/adversarial splits are excluded from training exports.
- Release-check remains required before any ranker/pack promotion.
```

## M17S: Automated Harvester Scale Run

Status: passed.

Frozen target:

```text
v0.1.0-alpha.10
commit: b4a5020
```

Scale run:

```text
command: semscrape alpha run runs/m17s/source-registry.yml --policy ranker-local-safe --record-evidence --privacy features-only --out runs/auto/m17s --force --no-respect-rate-limits --pack ecommerce
sources:                  102
bundles:                  102
domains/source groups:    25
fields_attempted:         464
coverage_rate:            0.678879
false_positive_rate:      0.002155
candidate_recall@40:      0.995633
bundle_audit_pass_rate:   1.000000
review_queue_items:       296
hard_negatives_created:   5278
```

Split checks:

```text
dev false_positive_rate:          0.002833
dev candidate_recall@40:          0.997167
holdout false_positive_rate:      0.000000
holdout candidate_recall@40:      0.990476
adversarial false_positive_rate:  0.000000
```

Safety result:

```text
features-only bundle audit pass rate: 100%
training dataset produced: no
ranker/pack promoted: no
review items eligible for global training: 0
holdout/adversarial split rows used for training: no
```

Report:

```text
docs/m17s_harvester_scale_report.md
```

## M18: Review Queue Triage and Trusted Label Conversion

Status: passed.

Question: Can the M17S harvester review queue be converted into trusted labels, hard negatives, candidate-generation fixes, and pack/ranker update candidates without poisoning the model?

Implemented commands:

```text
- semscrape review triage
- semscrape review export
- semscrape review apply
```

M17S triage:

```text
review_queue_items:        296
high_priority_items:       144
training_eligible_before_review: 0
false_positives:           1
candidate_recall_misses:   2
recoverable_abstentions:   141
low_margin_accepts:        146
plain_abstentions:         6
```

M18 batch conversion:

```text
reviewed_batch_size:       100
reviewed_items:            100
gold_hard_negatives:       1
candidate_generation_issues: 2
deferred_manual_reviews:   97
training_eligible_rows:    1
training_excluded_rows:    99
privacy_passed:            true
```

Safety result:

```text
No unverified accepted extraction was converted into a positive training label.
Holdout/adversarial rows remain excluded from training exports.
Recoverable abstentions remain deferred until explicit value review.
The M17S dev-split false positive became one reviewed gold hard-negative training row.
```

Decision:

```text
Do not train a new ranker or pack from M18 alone.
One reviewed hard-negative row is useful, but not enough for a model update.
Next data-moat step should acquire more trusted labels through oracle-backed sources and/or larger explicit review batches.
```

Report:

```text
docs/m18_review_queue_conversion_report.md
```

## M18B: Trusted Label Acquisition / Oracle Sources

Status: passed.

Question: Can semscrape generate many more gold/silver labels from trusted or oracle-backed sources without using raw extraction guesses as positives?

Implemented:

```text
- expected_mode: oracle in source registries.
- semscrape oracle resolve.
- semscrape oracle report.
- alpha run --resolve-oracles.
- Oracle mismatch/error rows in oracle-expected.jsonl.
- Oracle-backed expected values feed alpha-run canary/evidence labels.
- Oracle training-eligible evidence export.
- Oracle types: manual_expected, pypi_json, npm_registry, github_repo, json_ld.
```

Oracle label-yield run:

```text
sources_with_oracle:      25
fields_resolved:          98
fields_missing:           0
gold_labels_created:      98
silver_labels_created:    0
oracle_type:              manual_expected
split:                    train_candidate
```

Alpha run with oracle expected values:

```text
sources:                  25
fields_attempted:         98
coverage_rate:            0.724490
false_positive_rate:      0.000000
candidate_recall@40:      1.000000
bundle_audit_pass_rate:   1.000000
oracle_training_eligible_rows: 98
```

Safety result:

```text
Raw extraction outputs were not promoted to positives.
Oracle values were injected as expected values before evaluation.
Features-only bundle audit passed.
Holdout/adversarial training exclusions remain in the export logic.
No ranker or pack was trained or promoted.
```

Decision:

```text
M19 is now unblocked for a candidate evidence-driven ranker/pack update attempt.
Promotion must still require release-check against base, adversarial, external, and harvester suites.
```

Report:

```text
docs/m18b_oracle_label_acquisition_report.md
```

## M19: Evidence-Driven Ranker/Pack Update

Status: completed, no promotion.

Question: Can oracle-backed trusted labels improve the default ranker or a domain pack without regressing false-positive safety?

Dataset build:

```text
source: data/m18b/oracle-training-eligible-evidence.jsonl
dataset: data/m19/candidate-ranking-oracle.jsonl
candidate_rows: 3920
positive_rows: 186
hard_negative_rows: 1498
training_splits: train_candidate only
min_trust: silver
only_training_eligible: true
```

Group-aware split:

```text
train_rows: 2680
eval_rows: 1240
train_groups: 16
eval_groups: 9
```

Ranker candidate:

```text
model: models/candidate-ranker-vNext.json
model_card: models/candidate-ranker-vNext.md
training_rows: 2680
positives: 131
negatives: 2549
hard_negatives: 1091
```

Oracle eval split:

```text
candidate-ranker-v3:
  coverage_rate:       0.645161
  false_positive_rate: 0.064516
  candidate_recall@40: 1.000000

candidate-ranker-vNext:
  coverage_rate:       0.548387
  false_positive_rate: 0.000000
  candidate_recall@40: 1.000000
```

Ranker release-check:

```text
passed: false
promotion: keep_baseline
base_holdout_v3_coverage:    0.450000
base_holdout_vnext_coverage: 0.150000
base_holdout_vnext_fpr:      0.000000
adversarial_vnext_fpr:       0.000000
failed_gates:
  - base_coverage
  - coverage_not_regressed
```

Pack candidate:

```text
pack: packs/ecommerce-vNext
baseline: packs/ecommerce-v1
release_check: failed
promotion: keep_baseline
baseline_coverage:  0.800000
candidate_coverage: 0.150000
candidate_fpr:      0.000000
adversarial_fpr:    0.000000
```

Safety result:

```text
No unverified production positives were used.
Holdout/adversarial/monitor_only rows were excluded from the oracle-derived training build.
Candidate recall did not regress in the checked candidate/eval rows.
Adversarial false_positive_rate remained 0.
No default ranker or pack was promoted.
```

Decision:

```text
M19 proves the update loop can build candidate artifacts and reject unsafe or low-utility candidates.
The oracle labels were useful for safety, but too narrow and too docs/article/database-heavy to promote a general ranker or ecommerce pack.
Next evidence step should expand trusted oracle labels across ecommerce/listings/pricing and reserve oracle holdouts for evaluation.
```

Report:

```text
docs/m19_evidence_driven_update_report.md
```

## M19R: Ranker Update Diagnostics and Safe Coverage Preservation

Status: completed, no promotion.

Question: Can the oracle-trained safety signal be used without collapsing coverage on existing holdouts?

Diagnostic tooling:

```text
semscrape ranker diff
semscrape dataset balance
```

Baseline vs vNext oracle eval diff:

```text
rows: 31
false_positive_fixed: 2
coverage_lost_correct: 1
same_correct: 17
same_abstained: 11
```

Baseline vs vNext base holdout diff:

```text
rows: 20
coverage_lost_correct: 6
same_correct: 3
same_abstained: 11
loss_categories:
  ecommerce: price, rating, availability
  docs: page_title, install_command
  recipes: servings
```

Balanced training recipe:

```text
train_rows: 799
positives: 131
hard_negatives: 254
hard_negatives_per_positive_cap: 3
plain_negatives_per_positive_cap: 4
positive_weight: 10
hard_negative_weight: 2
negative_weight: 1
```

Balanced candidate:

```text
oracle_eval_coverage:       0.548387
oracle_eval_fpr:            0.000000
oracle_eval_recall@40:      1.000000
base_holdout_coverage:      0.550000
base_holdout_fpr:           0.000000
base_holdout_recall@40:     1.000000
adversarial_fpr:            0.000000
release_check_passed:       false
failed_gate:                base_coverage
promotion:                  keep_baseline
```

Decision:

```text
No replacement ranker, pack, or safety-veto policy is promoted.
vNext is useful as training signal, not as the default ranker or a simple veto yet.
The next bottleneck is trusted label distribution across ecommerce, listings, pricing, and base-holdout-like positives.
```

Report:

```text
docs/m19r_ranker_regression_diagnosis.md
```

## M20: Safety Veto + Positive Label Expansion

Status: completed, opt-in veto policy added.

Question: Can we use the oracle-trained safety signal to block known traps while preserving baseline coverage, and can we collect enough positive labels to make a future replacement ranker viable?

Implementation:

```text
policy: ranker-local-safe-veto
baseline ranker: candidate-ranker-v3
veto ranker: candidate-ranker-vNext
veto threshold: veto positive confidence below 0.60
behavior: block-only; never recovers candidates rejected by the baseline
```

Commands:

```text
semscrape ranker veto-eval
semscrape canary --policy ranker-local-safe-veto --veto-ranker models/candidate-ranker-vNext.json
```

Oracle eval:

```text
v3 coverage_rate:       0.645161
v3 false_positive_rate: 0.064516
v3 recall@40:           1.000000

veto coverage_rate:       0.548387
veto false_positive_rate: 0.000000
veto recall@40:           1.000000
vetoed rows:              3
false_positive_fixed:     2
coverage_lost_correct:    1
```

Base/adversarial:

```text
base_v3_coverage:       0.450000
base_veto_coverage:     0.450000
base_veto_fpr:          0.000000
adversarial_veto_fpr:   0.000000
coverage_loss_vs_v3:    0.000000
```

M20 release-check:

```text
passed: true
min_coverage: 0.427500
coverage_not_regressed: true
fpr_not_regressed: true
adversarial_false_positive_rate: true
```

Must-keep positives:

```text
file: data/regression/must_keep_positives.jsonl
rows: 6
usage: regression_only_not_training
families:
  - docs install_command
  - docs page_title
  - ecommerce availability
  - ecommerce price
  - ecommerce rating
  - recipes servings
must_keep_positive_veto_rate: 0.000000
```

Decision:

```text
ranker-local-safe-veto is available as an internal opt-in evaluation policy.
No default ranker, pack, or public policy is changed.
The veto passed the narrow M20 safety/coverage gate, but it needs broader external/regression validation before default promotion.
```

Defaults remain:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

Report:

```text
docs/m20_safety_veto_report.md
```
