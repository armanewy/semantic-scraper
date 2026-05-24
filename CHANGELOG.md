# Changelog

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
