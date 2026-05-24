# M16W Founder-Operated Wide External Corpus Report

Status: failed safety/recall gate, useful evidence captured.

M16W tested `v0.1.0-alpha.8` on a founder-operated wide external corpus. This is not a true outside-user cohort; it validates content/page generalization under a frozen protocol, not independent-user onboarding or spec-writing behavior.

## Protocol

- Frozen target: `v0.1.0-alpha.8`
- Policy: `ranker-local-safe`
- Operator: founder
- Mode: first-pass local replay from public pages
- Scope rules:
  - public pages only
  - no login
  - no paywall/CAPTCHA/proxy bypass
  - one or a few pages per site
  - expected values recorded before semscrape execution
  - no code/ranker/validator tuning during measurement

## Corpus

Generation attempted 68 public URLs. Robots/fetch/content checks skipped 8 initial URLs, and 6 heavy generated projects timed out during pilot execution. A supplemental lightweight batch was added to reach the volume gate.

Completed corpus:

```text
projects_completed:     54
fields_attempted:       267
domains/source groups:  14
bundle_audit_pass_rate: 1.000000
```

Source groups:

```text
article_quotes
database_sqlite
docs_django
docs_github
docs_mdn
docs_python
ecommerce_books
government_usa
package_pypi
python_org
reference_example
reference_iana
runtime_nodejs
standards_w3c
```

## Metrics

```text
coverage_rate:          0.629213
false_positive_rate:    0.026217
false_positives:        7
candidate_recall@40:    0.850187
candidate_missing:      40
abstention_rate:        0.370787
bundle_audit_pass_rate: 1.000000
```

Gate result:

```text
50+ projects/pages:                pass
8+ domains/source groups:          pass
200+ attempted fields:             pass
bundle audit pass rate = 100%:     pass
ranker-local-safe coverage >= 50%: pass
false_positive_rate <= 2%:         fail
candidate_recall@40 >= 95%:        fail
```

## False Positives

The final-result false-positive count is 7. Five of those are also candidate-recall failures where the expected value was not present in the top-40 candidate set, but the runtime still extracted a wrong fallback candidate. Under the M16F metric definition, extracted-wrong rows count as false positives even when candidate recall failed.

```text
database_sqlite_058 / first_section_heading
  expected: Common Links
  got:      Latest Release
  type:     wrong candidate

database_sqlite_058 / first_content_link
  expected: Home
  got:      Prior Releases
  type:     wrong candidate

docs_python introduction / first_section_heading
  expected: Table of Contents
  got:      3.1. Using Python as a Calculator
  type:     candidate missing + extracted wrong

docs_python controlflow / first_section_heading
  expected: Table of Contents
  got:      4.1. if Statements
  type:     candidate missing + extracted wrong

docs_python inputoutput / first_section_heading
  expected: Table of Contents
  got:      7.2.1. Methods of File Objects
  type:     candidate missing + extracted wrong

docs_python errors / first_section_heading
  expected: Table of Contents
  got:      8.5. Exception Chaining
  type:     candidate missing + extracted wrong

standards_w3c_056 / meta_description
  expected: W3C meta description
  got:      visible W3C body paragraph
  type:     candidate missing + extracted wrong
```

## Candidate Recall Gaps

Candidate recall failed the wide-corpus gate:

```text
candidate_recall@40: 0.850187
candidate_missing:   40 / 267
```

Repeated miss families:

```text
first_paragraph:         20
first_section_heading:   12
meta_description:         5
page_heading:             2
first_content_link:       1
```

Primary causes observed:

- Metadata values are often not represented as candidates.
- Long first paragraphs or generated/fallback text are over-filtered or not represented in top-K.
- Some docs pages surface sidebars, table-of-contents labels, or content headings in ways that make "first section" ambiguous.
- Public/government pages include banner/fallback content that should not be treated as main content.

## Measurement Fix

M16W found a measurement bug in `alpha summarize` and `pack gaps`: extracted-wrong rows with `candidate_recall=false` were not counted as false positives when the evidence export had no positive candidate row. The fix counts these rows as false positives when:

```text
record.status == extracted
label.status == labeled
candidate_recall == false
selected_candidate_id exists
```

This aligns `alpha summarize` with the M16F final-result metric definition.

## Artifacts

```text
runs/m16w/founder-wide-generation.json
runs/m16w/founder-wide-generation-supplemental.json
runs/m16w/founder-wide-pilot-run-results-resume.json
runs/m16w/founder-wide-pilot-run-results-supplemental.json
runs/m16w/founder-wide-summary.md
runs/m16w/founder-wide-gaps.md
runs/m16w/founder-wide-summary-corrected.md
runs/m16w/founder-wide-summary-corrected.json
data/intake/m16w-founder-wide-evidence.jsonl
```

## Decision

M16W does not pass. Do not invite true outside users on this evidence alone.

Next milestone should be M16W-R:

```text
fix candidate recall for metadata/paragraph/main-content candidates
prevent extraction when expected candidate is missing
convert the two true wrong-candidate rows into gold hard negatives
rerun founder-wide remediation and a fresh wide mini-holdout
```
