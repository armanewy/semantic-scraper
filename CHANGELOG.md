# Changelog

## v0.1.0-alpha.6 - 2026-05-23

Controlled public-alpha cohort target with corrected measurement semantics.

### Fixed

- `semscrape alpha summarize` now counts false positives only when the final field result is an extracted wrong value.
- Final abstentions with rejected wrong candidates in their traces are counted as abstentions, not false positives.
- `semscrape pack gaps` uses the same final-result false-positive definition.
- Evidence-store false-positive stats now require final `status = extracted`.

### Validation

M16C local stand-in cohort under corrected final-result metrics:

```text
projects/bundles:        25
domains:                 6
fields_attempted:        69
coverage_rate:           0.753623
false_positive_rate:     0.000000
candidate_recall_at_40:  1.000000
bundle_audit_pass_rate:  1.000000
```

This was a local external-style cohort, not the true outside-user cohort.

## v0.1.0-alpha.4 - 2026-05-23

Limited public-alpha candidate.

### Added

- `ranker-local-safe` high-precision policy preset.
- Default CLI extraction/pilot/canary policy now favors `ranker-local-safe`.
- Public-alpha documentation:
  - `docs/public_alpha.md`
  - `docs/known_limitations.md`
  - `docs/evidence_intake_runbook.md`
- GitHub issue templates for false positives, abstentions, candidate misses, spec help, pack requests, and evidence/privacy issues.
- `semscrape alpha summarize` for aggregating audited evidence bundles from an alpha cohort.

### Changed

- Ecommerce packs now use safer local thresholds by default.
- Candidate/ranker features include more local context and region flags for metadata panels, table-of-contents, glossary, breadcrumb, and code regions.
- Docs section gates now reject banners, hidden footer headings, footer columns, and sidebar-only content without rejecting legitimate main-content headings.
- First-listing, recent-title, and metadata-value gates are stricter on external-style pages.

### Validation

M15R public-alpha safety gate:

```text
M15 remediation:
  coverage_rate: 0.709678
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

M15R mini-holdout:
  coverage_rate: 0.900000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

regressions:
  original external FPR: 0.000000
  M14 fresh FPR:         0.000000
  M14R mini FPR:         0.000000
  base holdout FPR:      0.000000
  adversarial FPR:       0.000000
```

### Known Limits

This is a controlled public alpha, not a general web scraping guarantee. Abstention is expected when evidence is weak. Users should run canaries for their own page families before trusting a workflow.
