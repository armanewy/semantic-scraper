# M16R-Founder External Incident Report

## Summary

The founder-operated external cohort ran `v0.1.0-alpha.6` against fresh public pages as an outside-style preflight before inviting true outside users. It failed the safety gate:

```text
founder_external_alpha6:
  bundles: 16
  accepted_bundles: 15
  domains: 5
  fields_attempted: 75
  coverage_rate: 0.986667
  false_positive_rate: 0.333333
  false_positive_among_extracted: 0.337838
  candidate_recall_at_40: 0.933333
  bundle_audit_pass_rate: 0.937500
```

The failure was useful. It showed that `ranker-local-safe` still accepted too aggressively on fresh list, docs, table, and generic text pages, and it found a privacy export bug in one features-only bundle.

## Privacy Incident

| Project | Bundle | Failure type | Cause | Fix |
| --- | --- | --- | --- | --- |
| `reference_pypi_bs4_002` | `reference_pypi_bs4_002.zip` | `privacy_export_bug` | Features-only evidence retained `candidate_before_text` / `candidate_after_text` snippets that included HTML-like documentation examples. | Features-only export now strips candidate before/after/parent text, the privacy audit treats those keys as full candidate text, and bundle creation raises on features-only privacy violations. |

Privacy regression coverage:

- features-only bundles must not contain raw HTML, selectors, full candidate text, candidate context, raw values, before/after text, or parent text.
- unsafe features-only bundle creation fails loudly instead of producing a shareable bundle.

## False-Positive Incidents

The alpha.6 false positives were classified before remediation. True semantic false positives become gold hard negatives. Candidate misses are tracked separately because ranker training cannot recover a candidate that was not generated.

| Project | Domain | Field | Expected | Actual | Failure type | Fix type | Label action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `article_quotes_home_001` | article | `second_author` | second quote author | first quote author | `repeated_list_confusion`, `ranker_overconfident` | ordinal listing/list-card gate and safe margin default | gold hard negative |
| `article_quotes_humor_002` | article | `first_tag` | first quote tag | later tag | `repeated_list_confusion` | repeated-list ordinal/context gate | gold hard negative |
| `article_quotes_humor_002` | article | `second_author` | second quote author | first quote author | `repeated_list_confusion` | ordinal list-card gate | gold hard negative |
| `article_quotes_inspirational_004` | article | `second_author` | second quote author | first quote author | `repeated_list_confusion` | ordinal list-card gate | gold hard negative |
| `article_quotes_page2_003` | article | `second_author` | second quote author | first quote author | `repeated_list_confusion` | ordinal list-card gate | gold hard negative |
| `docs_iana_example_domains_001` | docs | `first_policy_rfc` | RFC value | section heading | `docs_nav_or_title_confusion` | RFC value gate | gold hard negative |
| `docs_iana_example_domains_001` | docs | `second_policy_rfc` | RFC value | section heading | `docs_nav_or_title_confusion` | RFC value gate | gold hard negative |
| `docs_python_appetite_001` | docs | `page_title` | HTML document title | page H1 | `docs_title_context_confusion` | document-title gate requires `title` element | gold hard negative |
| `docs_python_appetite_001` | docs | `main_heading` | main H1 | paragraph body text | `docs_title_context_confusion` | main-heading gate requires `h1` | gold hard negative |
| `docs_python_appetite_001` | docs | `tutorial_home` | tutorial navigation label | source-menu link | `docs_nav_or_title_confusion` | docs chrome action disqualifier and navigation-link intent gate | gold hard negative |
| `docs_python_interpreter_002` | docs | `page_title` | HTML document title | page H1 | `docs_title_context_confusion` | document-title gate requires `title` element | gold hard negative |
| `docs_python_interpreter_002` | docs | `main_heading` | main H1 | source-menu link | `docs_nav_or_title_confusion` | main-heading gate and docs chrome disqualifier | gold hard negative |
| `docs_python_interpreter_002` | docs | `second_section` | second section heading | first section heading | `repeated_list_confusion`, `docs_title_context_confusion` | section ordinal/context gate | gold hard negative |
| `ecommerce_books_light_001` | ecommerce | `product_type` | table value | table header label | `table_row_column_confusion` | metadata/table value gate rejects `th` labels | gold hard negative |
| `ecommerce_books_sapiens_005` | ecommerce | `product_type` | table value | table header label | `table_row_column_confusion` | metadata/table value gate rejects `th` labels | gold hard negative |
| `ecommerce_books_sharp_004` | ecommerce | `product_type` | table value | table header label | `table_row_column_confusion` | metadata/table value gate rejects `th` labels | gold hard negative |
| `ecommerce_books_soumission_003` | ecommerce | `product_type` | table value | table header label | `table_row_column_confusion` | metadata/table value gate rejects `th` labels | gold hard negative |
| `ecommerce_books_velvet_002` | ecommerce | `product_type` | table value | table header label | `table_row_column_confusion` | metadata/table value gate rejects `th` labels | gold hard negative |
| `listing_books_travel_001` | listings | `second_product_price` | second product price | first product price | `repeated_list_confusion` | listing ordinal price gate | gold hard negative |
| `listing_hockey_forms_002` | listings | `first_team` | first table team | pagination text | `table_row_column_confusion` | table data prompt requires table-cell context and rejects pagination | gold hard negative |
| `listing_hockey_forms_002` | listings | `first_year` | first table year | page heading number | `table_row_column_confusion` | table data prompt requires table-cell context | gold hard negative |
| `listing_hockey_forms_002` | listings | `first_wins` | first table wins | page heading number | `table_row_column_confusion` | table data prompt requires table-cell context | gold hard negative |
| `listing_hockey_forms_002` | listings | `first_losses` | first table losses | page heading number | `table_row_column_confusion` | table data prompt requires table-cell context | gold hard negative |
| `misc_example_domain_001` | misc | `purpose_sentence` | purpose paragraph | page title | `generic_text_overmatch` | generic sentence gate rejects headings and unsafe low-intent text | gold hard negative |
| `misc_example_domain_001` | misc | `more_info_link` | link text | paragraph text | `generic_text_overmatch` | link field gate requires anchor/href evidence | gold hard negative |
| `reference_pypi_bs4_002` | reference | `project_summary` | project summary | files-tab helper copy | `generic_text_overmatch`, `docs_nav_or_title_confusion` | docs/content region and generic text gates | gold hard negative |
| `reference_pypi_bs4_002` | reference | `project_tab` | tab label | project description paragraph | `generic_text_overmatch` | generic/link/tab context gates | gold hard negative |

## Candidate Recall Incidents

| Project | Field | Expected | Alpha.6 failure type | Remediation |
| --- | --- | --- | --- | --- |
| `article_quotes_page2_003` | `first_quote_text` | long quote text | `candidate_missing` from long leaf filtering/truncation | Candidate generator now allows longer leaf text and quote-text spans. |
| `docs_iana_example_domains_001` | `organization_name` | organization name | `candidate_missing`, source/spec issue | Remains the single founder remediation candidate miss; recorded as source/spec-shape issue rather than ranker failure. |
| `docs_python_appetite_001` | `documentation_label` | documentation label from full link title | `candidate_missing` from truncated visible label | Text validator can recover longer `title` attributes and documentation-label segments. |
| `listing_books_travel_001` | `second_product_title` | second product title | `candidate_missing` / listing ordinal weakness | Listing item prompts now understand second/third ordinal candidates. |
| `listing_hockey_forms_002` | `first_win_pct` | table percentage | `candidate_missing` within top 40 | Table-row and percentage context boosts improve table candidate ordering. |

## Remediation

M16R-Founder changed the public-alpha-safe posture in four areas:

- Privacy: features-only bundle generation now rejects raw HTML/full-text leaks before writing a bundle.
- Acceptance gates: `ranker-local-safe` now applies policy defaults for ranker confidence and margin during pilot/canary/extract flows, and final safe acceptance runs field-specific gates against both strict heuristic and ranker choices.
- Region and structure gates: repeated/list ordinals, docs title/navigation contexts, table row/column contexts, links, RFC values, generic sentence fields, and product metadata values now have narrower safety checks.
- Candidate recall: longer leaf text, title-attribute recovery, documentation label normalization, quote text, table percentage, and ordinal listing candidates were improved.

The remediated policy is intentionally conservative:

```text
ranker-local-safe:
  min_ranker_confidence: 0.90
  min_ranker_margin: 0.008
  min_validator_confidence: 0.75
  max_ranker_penalties: 0
  llm_enabled: false
```

## Remediation Results

Founder external rerun:

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

One founder project, `reference_pypi_requests_001`, timed out during the final rerun and is excluded from the extraction aggregate as an operational timeout.

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

The coverage drop is expected and acceptable for this remediation. The founder cohort showed that alpha.6 was too aggressive; alpha.7 restores abstention as the safety default. Coverage should be rebuilt later through candidate generation, domain packs, and field-specific evidence, not by loosening safety gates.

## Release Posture

M16R-Founder passes the founder-operated external remediation gate and is suitable to tag as `v0.1.0-alpha.7`.

It does not complete M16C true outside-user validation. The next cohort still needs unrelated users or genuinely independent projects to run the frozen target and produce audited features-only evidence bundles.
