# M15R Public-Alpha Safety Report

## Decision

```text
M15R: passed
public-alpha readiness: alpha.4 candidate
policy tested: ranker-local-safe
```

M15R restored false-positive safety after the M15 public-alpha readiness failure. The remediation intentionally favors abstention over coverage when evidence is weak.

## M15 Remediation Set

```text
pilots: 11
domains: 6
fields: 31
coverage_rate: 0.709678
false_positive_rate: 0.000000
abstention_rate: 0.290322
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

This fixes the M15 fresh set:

```text
before:
  coverage_rate: 0.741936
  false_positive_rate: 0.096774
  candidate_recall_at_40: 0.967742

after:
  coverage_rate: 0.709678
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000
```

The coverage drop is acceptable for the public-alpha-safe preset because the false-positive safety gate is the release blocker.

## Fresh M15R Mini-Holdout

```text
pilots: 4
domains: 4
fields: 10
coverage_rate: 0.900000
false_positive_rate: 0.000000
abstention_rate: 0.100000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

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
model_call_rate: 0.000000
```

Adversarial holdout:

```text
rows: 6
false_positive_rate: 0.000000
model_call_rate: 0.000000
```

Release-check:

```text
passed: true
promotion: promote_candidate
```

## Gate Result

| Gate | Target | Observed | Status |
| --- | ---: | ---: | --- |
| M15 remediation FPR | `0.000000` | `0.000000` | pass |
| M15 remediation recall@40 | `>= 0.950000` | `1.000000` | pass |
| M15R mini-holdout FPR | `<= 0.020000` | `0.000000` | pass |
| M15R mini-holdout recall@40 | `>= 0.950000` | `1.000000` | pass |
| M15R mini-holdout coverage | `>= 0.550000` | `0.900000` | pass |
| Regression FPR | `0.000000` | `0.000000` | pass |
| Base holdout FPR | `0.000000` | `0.000000` | pass |
| Adversarial FPR | `0.000000` | `0.000000` | pass |
| Bundle audit pass rate | `1.000000` | `1.000000` | pass |

## Release Posture

M15R is a public-alpha safety remediation pass. If this commit is tagged as `v0.1.0-alpha.4`, that tag should be treated as a limited public-alpha candidate, not a universal web robustness claim.

Known constraints:

- The public-alpha default should use `ranker-local-safe` where false positives matter.
- Abstention is expected on weak evidence.
- Users should run canaries for their own page families.
- Raw pilot pages and evidence DBs remain local/ignored.
- No unverified production positives should be used for base-ranker training.
