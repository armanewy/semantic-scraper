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
