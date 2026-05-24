# M16U Safe Coverage Recovery Report

Status: passed.

M16R-Founder restored safety and privacy, but `ranker-local-safe` became too conservative for a usable outside-user alpha. M16U recovered coverage by allowing low-margin ranker choices only when field-specific structural evidence is strong, while preserving hard abstention for known trap regions and ambiguous candidates.

## Changes

- Moved field-specific hard gates ahead of the ranker margin gate so unsafe top candidates are rejected before considering low-margin recovery.
- Added a narrow recoverable-abstention path for high-validator-confidence, structurally grounded candidates.
- Kept generic text conservative unless there is strong field/region evidence.
- Tightened recovery for quote/card ordinals, RFC anchors, truncated titles, and Python tutorial navigation links.
- Added regression tests for:
  - Python tutorial navigation link vs module index.
  - quote page title fields that mention "Quotes" but are not quote-text fields.
  - quote text fields rejecting author candidates.

## Results

Founder-operated external remediation set:

```text
bundles:                18
fields_attempted:       91
coverage_rate:          0.769231
false_positive_rate:    0.000000
candidate_recall@40:    0.989011
abstention_rate:        0.230769
bundle_audit_pass_rate: 1.000000
```

Fresh M16R mini-holdout:

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

Regression suites:

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

Artifacts:

```text
runs/m16u/founder-external-summary.md
runs/m16u/fresh-mini-holdout-summary.md
runs/m16u/founder-external-gaps.md
runs/m16u/fresh-mini-holdout-gaps.md
runs/m16u/base-holdout-ranker-local-safe.jsonl
runs/m16u/adversarial-holdout-ranker-local-safe.jsonl
data/intake/m16u-founder-external-evidence.jsonl
data/intake/m16u-fresh-mini-holdout-evidence.jsonl
```

## Decision

M16U passes. The next outside-user cohort target should use the M16U build, not `v0.1.0-alpha.7`, because alpha.7 is safe but over-abstains.

This remains preflight evidence. M16C is not complete until outside users/projects run the frozen target, produce audited features-only bundles, and pass the cohort gate without maintainer steering.
