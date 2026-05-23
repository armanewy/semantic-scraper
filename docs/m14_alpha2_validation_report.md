# M14 Alpha.2 Validation Report

Date: 2026-05-23

`v0.1.0-alpha.2` was tagged and pushed at commit `dd5a2aa5f21b4173cee9a5747ce56be82cd7b9ac`.

## Result

M14 did not pass release-readiness.

The M13R remediation remained effective on the original external-alpha regression set, but a fresh alpha.2 pilot set found new false positives and candidate-recall misses. The correct release decision is to keep alpha.2 as an internal validation tag and run a focused M14R remediation before any public alpha.

## Metrics

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

Base and adversarial holdouts:

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

## Fresh Failure Themes

- Listing item disambiguation: page/category headings can be selected for first product-title fields.
- Docs section disambiguation: documentation pages with survey/sidebar sections can confuse page title and first section fields.
- Pricing table disambiguation: plan prices need row/column anchoring instead of reusable scalar price selection.
- Candidate generation: exact expected price candidates were missing in two fresh fields.

## Decision

Do not promote `v0.1.0-alpha.2` to public alpha.

The next milestone should be M14R: convert these fresh failures into narrowly scoped safety gates, candidate-generation fixes, and gold hard negatives, then rerun the same fresh alpha.2 suite plus a new mini-holdout.
