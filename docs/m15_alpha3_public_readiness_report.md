# M15 Alpha.3 Public-Alpha Readiness Report

## Decision

```text
M15: executed
tag tested: v0.1.0-alpha.3
public alpha readiness: failed
next milestone: M15R
```

`v0.1.0-alpha.3` was tagged at:

```text
2b92586a9d3478999c144f98c851cdb104d72dfc
```

The tag is a valid frozen validation target, but it should not be promoted to public alpha. The fresh alpha.3 pilot set failed the false-positive safety gate.

## Fresh Alpha.3 Pilots

The fresh validation set used local replay snapshots under ignored pilot directories. Raw HTML, evidence DBs, bundles, and run artifacts remain uncommitted.

```text
pilots: 11
domains: 6
fields: 31
coverage_rate: 0.741936
false_positive_rate: 0.096774
abstention_rate: 0.258064
candidate_recall_at_40: 0.967742
bundle_audit_pass_rate: 1.000000
```

The run passed the candidate-recall, coverage, and privacy-audit gates, but failed the false-positive gate:

```text
target false_positive_rate <= 0.020000
observed false_positive_rate = 0.096774
```

## False Positives

M15 produced three false-positive rows:

| Pilot | Field | Expected | Observed | Failure class |
| --- | --- | --- | --- | --- |
| `ecommerce_business_001` | `first_product_price` | `£33.34` | `£43.14` | Later product price selected for first-product price. |
| `docs_pep8_001` | `status` | `Active` | `PEP 257` | Candidate missing for metadata value; ranker selected body link. |
| `article_python_insider_alpha3_001` | `first_recent_title` | `Python 3.15.0 beta 1 is here!` | `Python 3.14.5 is out!` | Featured h1 selected for first recent h3 post title. |

These should become M15R gold hard negatives or spec/candidate-generation corrections. Do not train from accepted alpha.3 outputs as positive labels by default.

## Regression Suites

Original external alpha regression:

```text
pilots: 5
domains: 4
fields: 15
coverage_rate: 0.933333
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

M14 fresh remediation regression:

```text
pilots: 6
domains: 5
fields: 18
coverage_rate: 0.777778
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

M14R mini-holdout regression:

```text
pilots: 3
domains: 3
fields: 7
coverage_rate: 0.714286
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

Base holdout:

```text
rows: 20
coverage_rate: 0.950000
false_positive_rate: 0.000000
candidate_recall_at_40: 1.000000
```

Adversarial holdout:

```text
rows: 6
coverage_rate: 0.000000
false_positive_rate: 0.000000
```

The regression suites stayed clean. The failure is fresh-page generalization, not regression on known suites.

## Evidence Loop

Alpha.3 evidence intake accepted all 11 valid bundles:

```text
records: 31
trust_level_counts:
  gold: 31
field_type_counts:
  text: 24
  price: 7
positive_candidate_rows: 111
hard_negative_candidate_rows: 594
```

Pack gap analysis reported:

```text
abstentions: 8
candidate_missing: 1
validator_rejected_positive_candidates: 8
hard_negatives: 594
```

Repeated trap families included position-path candidates, tag/sidebar/footer/breadcrumb text, and ecommerce price-card confusions.

## Release Decision

Do not promote `v0.1.0-alpha.3` to public alpha.

M15R should remediate:

- first-item price/title ordering across repeated ecommerce cards
- metadata key/value extraction for PEP-style definition lists
- feed-region distinction between featured post and recent-list post titles
- candidate recall for metadata scalar values
- release-check coverage for fresh external-style suites

Coverage should be allowed to drop during M15R if necessary. The product claim still depends on abstaining rather than silently returning wrong values.
