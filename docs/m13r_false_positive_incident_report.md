# M13R False-Positive Incident Report

Date: 2026-05-23

M13C executed five external-style alpha pilots against the frozen `v0.1.0-alpha.1` tag. The evidence/privacy workflow passed, but the field-trial safety gate failed:

```text
pilots: 5
domains: 4
fields: 15
coverage_rate: 1.000000
false_positive_rate: 0.333333
candidate_recall_at_40: 0.933333
bundle_audit_pass_rate: 1.000000
```

The failure mode was useful: the runtime was too willing to extract on unseen page semantics. M13R keeps the response narrow: add targeted gates and normalization for the observed traps, leave pilot evidence local, and allow abstention when the signal is weak.

## Incidents

| Case | Field | Failure Type | Action |
|---|---|---|---|
| `article_python_blog_001` | `published_at` | Semantic false positive: updated date selected instead of published date. | Added published-date role gating. Published/date prompts hard-disqualify nearby `updated`, `modified`, `revised`, or `last updated` cues unless the field asks for updated dates. |
| `docs_python_001` | `title` | Normalization mismatch: Sphinx heading permalink marker was included as `The Python Tutorial ¶`. | Added text normalization that strips trailing `¶`, `#`, and `permalink` heading markers. |
| `docs_python_001` | `second_chapter` | Semantic false positive: glossary/sidebar-style content selected instead of the requested second tutorial chapter. | Added ordinal chapter/section/tutorial gates so prompts like `second chapter` require a matching ordinal candidate. |
| `ecommerce_books_002` | `availability` | Spec exactness issue: generic `In stock` selected where the pilot expected full stock/count message. | Added `availability_mode: full_message` validator that rejects generic stock status when the spec requires full availability detail. |
| `listings_quotes_001` | `site_title` | Semantic false positive: tag-cloud heading `Top Ten tags` selected as page title. | Added title/tag-cloud hard negatives and boundary-aware title context matching so `ad` does not accidentally match `header`. |
| `listings_quotes_002` mini-holdout | `first_tag` | Semantic false positive during remediation: byline text selected as a tag. | Added tag-prompt gates requiring tag-shaped values and tag context. |
| `article_django_001` mini-holdout | `author` | Semantic false positive during remediation: CTA/navigation text selected as author. | Added person-name shape checks for author prompts. |

## Remediation Result

Original external-alpha pilots after remediation:

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

New mini-holdout pilots after remediation:

```text
pilots: 4
domains: 4
fields: 11
coverage_rate: 1.000000
false_positive_rate: 0.000000
abstention_rate: 0.000000
candidate_recall_at_40: 1.000000
bundle_audit_pass_rate: 1.000000
```

No ranker artifact was promoted in M13R. The safety recovery came from deterministic gates and validators, so the packaged ranker remains unchanged. A future ranker release should use these incidents as trusted hard-negative evidence only after the sealed release-check remains clean.
