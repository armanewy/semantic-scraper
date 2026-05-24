# M15R Public-Alpha Incident Report

## Summary

M15 executed against `v0.1.0-alpha.3` and blocked public alpha because fresh pilots produced false positives:

```text
fresh_alpha3:
  pilots: 11
  domains: 6
  fields: 31
  coverage_rate: 0.741936
  false_positive_rate: 0.096774
  candidate_recall_at_40: 0.967742
  bundle_audit_pass_rate: 1.000000
```

The evidence/privacy loop worked. The failure was correctness: unseen page semantics still let the ranker/validators accept wrong candidates.

## Incident Rows

| Pilot | Domain | Field | Expected | Actual | Failure type | Fix type | Label action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ecommerce_business_001` | ecommerce | `first_product_price` | `£33.34` | `£43.14` | `semantic_false_positive`, `ranker_overconfident` | First-listing price gate for repeated product-card regions. | Gold hard negative for later-card price. |
| `docs_pep8_001` | docs | `status` | `Active` | `PEP 257` | `candidate_present_but_ranker_overconfident`, `validator_too_permissive` | Metadata value gate for definition-list status fields; require key/value alignment and reject body/link/code candidates. | Gold hard negative for body link. |
| `article_python_insider_alpha3_001` | article | `first_recent_title` | `Python 3.15.0 beta 1 is here!` | `Python 3.14.5 is out!` | `semantic_false_positive`, `region_confusion` | Recent-list title gate; reject featured page h1 when prompt asks for first recent h3/list item. | Gold hard negative for featured h1. |
| `docs_django_tutorial_001` | docs regression | `first_tutorial_section` | `Creating a project` | `Django Developer Survey` | `region_confusion`, `validator_too_permissive` | Section-region gate rejects banners, hidden footer headings, and footer columns while allowing main content headings inside pages with sidebars. | Gold hard negative for survey/banner heading. |
| `docs_django_tutorial_001` | docs regression | `server_section` | `The development server` | `Django Links` | `region_confusion`, `validator_too_permissive` | Section-region gate rejects visually-hidden/footer navigation headings. | Gold hard negative for hidden footer heading. |

## Remediation

M15R added a high-precision local policy:

```text
ranker-local-safe:
  min_confidence: 0.78
  min_margin: 0.18
  min_validator_confidence: 0.75
  max_ranker_penalties: 0
  llm_enabled: false
```

It also added targeted gates and features for:

- first repeated listing/product-card prices
- recent h3/list item titles vs featured h1 titles
- metadata definition-list values vs body/link/code candidates
- unsafe docs section regions: banners, visually-hidden footer headings, footer columns, navigation, table-of-contents/sidebar-only regions
- rendered/structural region flags for metadata panels, breadcrumb, toc, glossary, and code regions

The broad sidebar context gate was narrowed. M15R now rejects explicit non-content selectors/regions without disqualifying legitimate main tutorial headings that happen to live in a page layout with a sidebar.

## Label Safety

No unverified accepted pilot outputs were used as positive training labels. True semantic false positives are treated as gold hard negatives. Ambiguous/spec issues remain review items rather than automatic positives.

## Artifacts

- M15 blocked readiness report: `docs/m15_alpha3_public_readiness_report.md`
- M15 remediation summary: `runs/m15r/m15-remediation-summary.md`
- M15R mini-holdout summary: `runs/m15r/mini-holdout-summary.md`
- Original external regression: `runs/m15r/original-external-alpha-regression-summary.md`
- M14 fresh regression: `runs/m15r/m14-fresh-remediation-regression-summary.md`
- M14R mini-holdout regression: `runs/m15r/m14r-mini-holdout-regression-summary.md`
- Base holdout: `runs/m15r/base-holdout-ranker-local-safe.jsonl`
- Adversarial holdout: `runs/m15r/adversarial-holdout-ranker-local-safe.jsonl`
- Release-check: `runs/m15r/ranker-local-safe-release-check.json`
