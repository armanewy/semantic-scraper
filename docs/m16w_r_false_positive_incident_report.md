# M16W-R False-Positive Incident Report

Status: remediated for the founder-wide corpus and fresh mini-holdout.

## Founder-Wide Baseline

M16W baseline false positives:

```text
false_positives:      7
false_positive_rate:  0.026217
```

Main categories:

```text
candidate_missing_then_wrong_extracted:
  expected candidate was not in top 40, but ranker-local-safe still accepted a plausible wrong value.

spec_ambiguity / generated expected-value issue:
  generated expectations pointed at UI chrome or unstable generic text rather than the requested main-content field.

first-section ordinal confusion:
  local h2:nth-of-type(1) selectors allowed later section headings to look like first section headings.

metadata_vs_main_content:
  body paragraph selected for meta_description because <meta> tags were skipped.
```

Fixes:

```text
metadata_vs_main_content:
  Include <meta> candidates and require meta-description candidates for meta_description fields.

first-section ordinal confusion:
  Annotate first valid main-content section candidate and block later section headings for first-section prompts.

candidate_missing_then_wrong_extracted:
  Keep missing-candidate cases abstained unless positive field evidence is strong.

spec_ambiguity:
  Remove invalid generated fields from the remediation set instead of training on them.
```

Founder-wide remediation result:

```text
false_positives:      0
false_positive_rate:  0.000000
```

## Fresh Mini-Holdout

Fresh mini-holdout false positives before the final document-title gate:

```text
false_positives:      1
false_positive_rate:  0.016393
```

Incident:

```text
project:     standards_017_standards_w3c_accessibility
field:       page_title
expected:    Introduction to Web Accessibility | Web Accessibility Initiative (WAI) | W3C
actual:      W3C homepage
type:        semantic_false_positive
candidate:   expected candidate was present; wrong title-like candidate was accepted
label:       gold hard negative for future title/domain-pack training
```

Final fix:

```text
HTML document-title prompts now require the real <head><title> candidate.
SVG/logo <title> elements are rejected with ranker_document_title_required.
```

Final fresh mini-holdout result:

```text
false_positives:      0
false_positive_rate:  0.000000
```
