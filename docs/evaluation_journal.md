# Evaluation Journal

This doc keeps the milestone-heavy evaluation narrative out of the README. The canonical full ledger remains [MILESTONES.md](../MILESTONES.md); this journal is the shorter product-facing history of what was tried, what passed, what failed, and which defaults changed.

## Current status snapshot

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
M21 veto distillation: completed, broad veto not promoted
M22 trap-only veto promotion trial: implemented as opt-in
M22E trap-only veto evaluation: executed, promotion blocked
M16C true outside-user cohort: pending
```

Defaults remain:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

## What the alpha history showed

The first external-style alpha execution used the frozen `v0.1.0-alpha.1` target. It proved that the evidence/privacy loop worked, but failed the field-trial safety gate because unseen page semantics produced false positives. M13R remediated those incidents with narrow deterministic gates and validators, then reran the original pilots and a new mini-holdout with zero observed false positives. See [M13R false-positive incident report](m13r_false_positive_incident_report.md).

`v0.1.0-alpha.2` was an internal validation tag for the M13R build. It passed the original external-alpha regression suite, but M14 fresh pilots found new false positives and candidate-recall misses, so it was not promoted to public alpha. M14R converted those failures into targeted normalization, region, listing-order, title, and plan-price gates. See [M14 alpha.2 validation report](m14_alpha2_validation_report.md) and [M14R fresh-alpha incident report](m14r_fresh_alpha_incident_report.md).

`v0.1.0-alpha.3` was the M14R-remediated validation tag. M15 tested it against a larger fresh pilot set and found that known regression suites stayed clean, but fresh-pilot false-positive rate was `0.096774`, so it was not public-alpha ready. See [M15 alpha.3 public-readiness report](m15_alpha3_public_readiness_report.md).

`v0.1.0-alpha.4` introduced the conservative `ranker-local-safe` public-alpha preset and restored zero observed false positives on the accumulated regression suites. See [M15R public-alpha safety report](m15r_public_alpha_safety_report.md).

`v0.1.0-alpha.5` added public-alpha onboarding/tooling, but it should not be used for the true outside-user cohort because `alpha summarize` overcounted final abstentions with rejected trace candidates as false positives.

`v0.1.0-alpha.6` fixed that measurement bug. The M16C local stand-in cohort passed safety under corrected final-result metrics:

```text
bundles:                25
fields_attempted:       69
coverage_rate:          0.753623
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
abstention_rate:        0.246377
bundle_audit_pass_rate: 1.000000
```

That was preflight evidence, not a completed outside-user field trial. A broader founder-operated external cohort then found that alpha.6 was still too aggressive on fresh pages:

```text
coverage_rate:          0.986667
false_positive_rate:    0.333333
candidate_recall@40:    0.933333
bundle_audit_pass_rate: 0.937500
```

M16R-Founder fixed the features-only privacy leak, added narrower safety gates for repeated lists, docs navigation/title contexts, table row/column fields, and generic text overmatches, and made `ranker-local-safe` deliberately conservative:

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

M16W widened founder-operated validation to 54 projects, 14 source groups, and 267 attempted fields. Privacy and coverage passed, but false-positive rate and candidate recall failed:

```text
coverage_rate:          0.629213
false_positive_rate:    0.026217
candidate_recall@40:    0.850187
bundle_audit_pass_rate: 1.000000
```

See [M16W founder-wide report](m16w_founder_wide_report.md).

M16W-R remediated the wide-corpus blocker with metadata candidates, fast sibling-aware structural selectors, first-section and repeated-card ordinal safety, paragraph-specific evidence, quote/product safe recovery, document-title head-only gating, and cleanup of invalid generated expected-value rows:

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

- [M16W-R candidate recall incident report](m16w_r_candidate_recall_incident_report.md)
- [M16W-R false-positive incident report](m16w_r_false_positive_incident_report.md)

M16C true outside-user testing remains pending until outside users/projects reproduce the workflow without direct maintainer steering.

## Evidence and ranker update history

M17 added a local automated evidence harvester. It collects privacy-safe evidence continuously without turning raw extractions into positive training labels:

```bash
semscrape alpha run sources/external.yml \
  --policy ranker-local-safe \
  --privacy features-only \
  --out runs/auto/latest
```

The harvester writes `summary.md`, `intake.jsonl`, `gaps.md`, `review-queue.jsonl`, per-source bundles, and a `harvest-manifest.json`. It enforces split metadata (`dev`, `holdout`, `adversarial`, `monitor_only`, `train_candidate`) and review-oriented trust boundaries. It does not train or promote rankers/packs. See [Automated External Evidence Harvester](automated_evidence_harvester.md).

M17S ran the harvester across 102 public-page replay sources and passed the scale gate: bundle audit pass rate `1.000000`, false-positive rate `0.002155`, and candidate recall@40 `0.995633`. See [M17S Harvester Scale Report](m17s_harvester_scale_report.md).

M18 added maintainer review commands for converting harvester queue items into trusted labels without poisoning the ranker:

```bash
semscrape review triage runs/auto/latest/review-queue.jsonl --out runs/review/triage.md
semscrape review export runs/auto/latest/review-queue.jsonl --limit 100 --priority high --out runs/review/batch.jsonl
semscrape review apply runs/review/batch-reviewed.jsonl --intake runs/auto/latest/intake.jsonl --out data/review/training-eligible-evidence.jsonl --report runs/review/trust-conversion.json
```

The M18 pass converted the M17S dev-split false positive into one reviewed gold hard-negative training row, classified two candidate misses as candidate-generation issues, and left recoverable abstentions deferred until explicit value review. See [M18 Review Queue Conversion Report](m18_review_queue_conversion_report.md).

M18B added oracle-backed expected values via `semscrape oracle resolve`, `semscrape oracle report`, and `semscrape alpha run --resolve-oracles`. Supported oracle types are `manual_expected`, `pypi_json`, `npm_registry`, `github_repo`, and `json_ld`. The M18B run generated 98 gold oracle-backed labels and 98 training-eligible evidence rows without using raw extraction guesses as positives. See [M18B Oracle Label Acquisition Report](m18b_oracle_label_acquisition_report.md).

M19 used the M18B oracle labels to build an evidence-derived candidate-ranking dataset with 3,920 rows, 186 positives, and 1,498 hard negatives. A `candidate-ranker-vNext` and `ecommerce-vNext` pack candidate were trained and release-checked. Both kept false positives at zero on the checked suites, but both lost too much coverage, so neither was promoted. The packaged default remains `candidate-ranker-v3`, and the current ecommerce pack remains `packs/ecommerce-v1`. See [M19 Evidence-Driven Ranker/Pack Update Report](m19_evidence_driven_update_report.md).

M19R diagnosed the M19 coverage regression and added `semscrape ranker diff` plus `semscrape dataset balance` for future update attempts. The oracle-trained candidate fixed two oracle-eval false positives but lost correct base/ecommerce rows; a balanced recipe improved base holdout coverage while preserving zero FPR, but still did not clear the release gate. No replacement ranker, pack, or veto policy was promoted. See [M19R Ranker Regression Diagnosis](m19r_ranker_regression_diagnosis.md).

M20 added an internal opt-in `ranker-local-safe-veto` policy and `semscrape ranker veto-eval`. The veto used `candidate-ranker-v3` for normal extraction and let `candidate-ranker-vNext` block accepted candidates only when its positive-confidence score was below the veto threshold. On M20 checks it fixed the two oracle-eval false positives, preserved base-holdout coverage at `0.450000`, and kept adversarial FPR at `0.000000`. Defaults did not change. See [M20 Safety Veto Report](m20_safety_veto_report.md).

M20P, M21, M22, and M22E kept the veto work opt-in. The broad veto reduced false positives but was too coverage-destructive. The trap-only veto was more focused, but promotion was blocked because it did not reduce observed false positives in the accumulated evaluation and vetoed known-correct rows. See:

- [M20P Veto Promotion Readiness Report](m20p_veto_promotion_readiness_report.md)
- [M21 Veto Distillation Report](m21_veto_distillation_report.md)
- [M22 Trap-Only Veto Promotion Trial](m22_trap_only_veto_promotion_trial.md)
- [M22E Trap-Only Veto Evaluation Report](m22e_trap_only_veto_evaluation_report.md)

## Release discipline

No milestone in this journal promotes unverified accepted production outputs as positive global training labels. Promotion still requires release checks against base, adversarial, external, and harvester-derived suites, with privacy audits for shared evidence bundles.
