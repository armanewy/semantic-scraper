# M16W-R Candidate Recall Incident Report

Status: remediated.

The M16W founder-operated wide corpus initially reported low candidate recall:

```text
fields_attempted:       267
candidate_recall@40:    0.850187
candidate_missing:      40
false_positive_rate:    0.026217
```

Triage showed two different failure modes:

```text
metadata candidate missing:
  <meta> tags were skipped before candidate generation.

generated expected-value/spec ambiguity:
  broad generated fields expected UI chrome or unstable generic text:
  - Table of Contents
  - Skip to main content
  - Django Developer Survey
  - In this article
  - official-site banners
  - fallback notices
  - arbitrary first links in code-heavy docs pages
  - long/truncated first-paragraph slices
```

Actions:

```text
candidate generation:
  - Include metadata candidates from <meta content=...>.
  - Use attribute text as candidate text for non-visible value-bearing elements.
  - Replace expensive per-candidate unique-selector probing with deterministic sibling-aware structural selectors.

ranking/gates:
  - Meta-description fields require a real meta-description candidate.
  - First-section fields annotate and prefer the earliest valid main-content section heading.
  - First-link fields reject later anchor ordinal candidates.
  - Repeated quote/product/listing fields preserve sibling ordinal evidence.
  - HTML document-title fields require the real <head><title> candidate, not SVG/logo title text.
  - Paragraph prompts prefer <p> candidates in main/content regions and reject non-paragraph text.

corpus hygiene:
  - Invalid generated fields were removed from the M16W remediation measurement set instead of being treated as model hard negatives.
  - Removed rows were classified as spec/expected-value issues, not trusted positive or negative training labels.
```

Founder-wide remediation result:

```text
fields_attempted:       257
coverage_rate:          0.692607
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
bundle_audit_pass_rate: 1.000000
```

Fresh mini-holdout result:

```text
projects/pages:         16
source groups:          7
fields_attempted:       61
coverage_rate:          0.721311
false_positive_rate:    0.000000
candidate_recall@40:    1.000000
bundle_audit_pass_rate: 1.000000
```

Label policy:

```text
true semantic false positives:
  gold hard negatives

candidate missing:
  candidate-generation or ranking recall issue

generated expected-value/spec ambiguity:
  excluded from remediation measurement
  not used as positive labels
  not used as hard negatives
```
