# M14R Fresh Alpha Incident Report

M14 showed that `v0.1.0-alpha.2` fixed the original external-alpha failures but still failed on fresh pilots:

```text
fresh alpha.2 pilots:
  pilots: 6
  domains: 5
  fields: 18
  coverage_rate: 0.722223
  false_positive_rate: 0.222222
  candidate_recall_at_40: 0.888889
```

The evidence/privacy path worked, so M14R used the fresh failures as gold hard-negative or correction evidence while keeping raw pilot artifacts local and ignored.

## Incidents

| Pilot | Field | Expected | Observed | Type | Remediation |
| --- | --- | --- | --- | --- | --- |
| `ecommerce_travel_listing_001` | `first_product_title` | `It's Only the Himalayas` | Later product title | Semantic false positive | Added first-listing DOM-order evidence and ranker gate for later listing candidates. |
| `ecommerce_travel_listing_001` | `first_product_price` | `£45.17` | Candidate recall miss from mojibake currency text | Normalization / recall miss | Normalized mojibake pound symbols during value extraction and expected-value matching. |
| `docs_django_tutorial_001` | `first_tutorial_section` | `Creating a project` | Paragraph inside the section | Semantic false positive | Required section prompts to resolve to h2/h3/h4 headings instead of body paragraphs. |
| `docs_django_tutorial_001` | `second_chapter` regression risk | Chapter link | Chapter link could be over-constrained by section rules | Gate overreach | Kept chapter prompts under ordinal logic; section-heading gates no longer apply to chapter fields. |
| `pricing_bootstrap_fresh_001` | `page_title` | `Pricing` | Price value | Semantic false positive | Main/page title prompts now reject price-shaped candidates. |
| `pricing_bootstrap_fresh_001` | `pro_plan_price` | `$15` | Wrong plan price | Semantic false positive | Added plan-context price gate so plan prices must appear in the requested plan region. |
| `article_python_blog_fresh_001` | `title` | `Python 3.14.0 beta 1 is here!` | Section heading `New features` | Semantic false positive | Main article/post title prompts now require a page-heading candidate. |

## Additional Mini-Holdout Finding

The first mini-holdout run found a docs-navigation trap:

```text
field: first_section
expected: Basic Usage
observed: Navigation
```

This was a real generalized region-awareness gap, not a pilot-specific string issue. M14R added a section-region gate for navigation, related, table-of-contents, previous/next, and source-link regions. A separate final mini-holdout was then created for the final gate.

## Final M14R Results

```text
fresh alpha.2 remediation set:
  pilots: 6
  domains: 5
  fields: 18
  coverage_rate: 0.777778
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

final fresh mini-holdout:
  pilots: 3
  domains: 3
  fields: 7
  coverage_rate: 0.714286
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

base holdout:
  coverage_rate: 0.950000
  false_positive_rate: 0.000000
  candidate_recall_at_40: 1.000000

adversarial holdout:
  false_positive_rate: 0.000000
```

`ranker release-check` passed against the prior M13R base-holdout baseline and the current adversarial holdout.

No ranker artifact was promoted in M14R. The packaged default remains `candidate-ranker-v3`; M14R restored safety through deterministic normalization, region gates, and ranker decision gates.
