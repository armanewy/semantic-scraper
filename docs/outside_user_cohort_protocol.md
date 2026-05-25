# Outside-User Cohort Protocol

Status: pending. This document defines how to run a true outside-user cohort. It is not evidence that the cohort has already completed.

## Purpose

Validate semscrape on real user projects without changing code, rankers, packs, thresholds, validators, or safety gates during the run.

The cohort is meant to answer two questions:

- Can outside users set up local projects, write field specs, run the safe policy, and produce audited evidence bundles without maintainer steering?
- Does the frozen build stay safe on fresh projects where the original author did not tune against the pages?

A failed cohort is a useful outcome. It should produce labeled failures and incidents first, then remediation work on a new commit or tag.

## Scope Boundaries

Keep these validation sets separate:

| Evidence type | Purpose | Can influence code before freeze? | Can influence code during cohort? | Can feed training by default? |
|---|---|---:|---:|---:|
| Train/dev corpora | Build rankers, tune gates, and test candidate generation. Examples include `corpus/base_train/`, `corpus/base_dev/`, `corpus/ood_dev/`, and reviewed `train_candidate` evidence. | yes | no | yes, if trusted and training-eligible |
| Regression suites | Prevent known failures from returning. Examples include accumulated alpha pilots, incident reproductions, and `data/regression/*`. | yes | no | hard negatives only when explicitly reviewed and non-holdout |
| Sealed holdouts | Release-candidate evaluation only. Examples include `corpus/base_holdout/`, `corpus/adversarial_holdout/`, and `corpus/ood_holdout/`. | no, except to decide pass/fail | no | no |
| True outside-user cohort | Independent user/project validation on a frozen build. | no, once invited | no | no positive training labels unless separately reviewed or oracle-backed |

Do not merge these categories in reports. The outside-user cohort is not a training set, not a dev set, and not a replacement for sealed holdouts.

## Cohort Target

Minimum target:

- 10 to 20 outside-user projects.
- At least 5 domains or source groups.
- At least 100 attempted fields across the cohort.
- No single project should contribute more than 30% of attempted fields unless the report calls out the skew.

Suggested domains include ecommerce, article/news, docs/reference, listings/search results, pricing/tables, package/repository pages, events, recipes, and jobs.

A project is one user-owned local workflow with its own spec, input HTML or replay snapshots, and evidence database. Multiple pages may belong to one project when they share the same workflow.

## Frozen-Run Rules

Before inviting participants:

1. Choose the exact target commit and, preferably, a version tag.
2. Record:
   - git commit SHA
   - git tag, if present
   - package version
   - policy, usually `ranker-local-safe`
   - pack, if any
   - `semscrape ranker info` output
   - Python version and OS family
3. Run the standard release checks for that commit.
4. Create the cohort run directory, for example `runs/outside-user-cohort/<tag-or-sha>/`.

During the cohort:

- Do not merge or apply code changes for cohort failures.
- Do not change ranker artifacts, packs, thresholds, validators, policy defaults, or safety gates.
- Do not rerun failed projects with a patched build and count them in the same cohort.
- Do not tune project specs after seeing extraction results and then count the tuned rerun as the frozen result.
- Do not label failures incrementally to guide mid-run fixes.
- If a privacy leak or severe false-positive pattern appears, stop the cohort, write an incident report, and restart later on a new frozen target. Do not resume under the same cohort ID after remediation.

Allowed during participant setup:

- Users may install semscrape, create specs, capture local snapshots, and ask setup questions before their project is frozen.
- Users may fix their own syntax errors or missing files before the frozen run.
- Maintainers may answer operational questions, but should not rewrite specs, inspect private raw HTML, or suggest threshold changes for a specific failing page.

Freeze each project before its final measured run by saving the spec, manifest, input/snapshot references, policy, pack, and required-field list. After that point, all extraction outcomes are measured as-is.

## Standard Workflow

Per project:

```bash
semscrape doctor
semscrape ranker info
semscrape canary manifest.yml \
  --policy ranker-local-safe \
  --record-evidence \
  --evidence-db .semscrape/evidence.db \
  --evidence-privacy redacted \
  --out runs/canary.jsonl
semscrape evidence bundle .semscrape/evidence.db \
  --privacy features-only \
  --out semscrape-evidence-bundle.zip
semscrape evidence audit semscrape-evidence-bundle.zip
```

For repo-structured pilot projects, the equivalent is:

```bash
semscrape pilot run PROJECT_DIR --policy ranker-local-safe
semscrape pilot report PROJECT_DIR --out PROJECT_DIR/runs/outside-user-scorecard.md
```

Maintainer aggregation:

```bash
semscrape alpha summarize cohort-bundles/*.zip \
  --out runs/outside-user-cohort/aggregate-summary.md
semscrape evidence intake cohort-bundles/*.zip \
  --out runs/outside-user-cohort/intake.jsonl
semscrape pack gaps runs/outside-user-cohort/intake.jsonl \
  --out runs/outside-user-cohort/gaps.md
```

If a project cannot share a bundle, record a local-only scorecard and privacy decision. Do not include unverifiable local-only rows in aggregate safety claims unless the report clearly separates them from audited bundles.

## Required Outputs

The cohort report must include:

- Aggregate summary with cohort size, domains, attempted fields, metrics, command lines, frozen commit/tag, and policy/pack.
- Per-project scorecard with project ID, domain, pages, attempted fields, required fields, coverage, false positives, abstentions, candidate recall@40, privacy audit status, and notes about user assistance.
- False-positive artifacts for every extracted wrong value, using record IDs, field names, expected/actual values when shareable, selected candidate metadata, failure reason, candidate recall status, and privacy mode.
- Abstention summary grouped by field, domain, failure reason, candidate-present status, and whether the abstention was expected safety behavior or recoverable.
- Candidate recall summary with numerator, denominator, missing-candidate cases, and affected field/domain families.
- Privacy audit result for every bundle and aggregate bundle audit pass rate.
- Incident report when false positives, privacy leaks, candidate recall misses, or measurement bugs block promotion.

Suggested run directory:

```text
runs/outside-user-cohort/<tag-or-sha>/
  freeze.md
  aggregate-summary.md
  per-project-scorecards/
  false-positive-artifacts.jsonl
  abstention-summary.md
  candidate-recall-summary.md
  privacy-audit-summary.md
  intake.jsonl
  gaps.md
  incident-report.md
```

## Required Metrics

Use final field outcomes, not rejected trace candidates, for the main cohort metrics.

Report at least:

- `fields_attempted`: number of field extraction attempts in audited evidence rows.
- `coverage_rate`: extracted final values divided by fields attempted.
- `false_positive_rate`: extracted wrong final values divided by fields attempted.
- `false_positive_among_extracted`: extracted wrong final values divided by extracted final values.
- `abstention_rate`: final abstentions divided by fields attempted.
- `candidate_recall_at_40`: fields where the expected candidate appears in the top 40 candidates divided by expected-present fields with recall evidence.
- `candidate_recall_denominator`: denominator used for candidate recall@40.
- `required_field_success_rate`: required fields extracted correctly divided by required fields declared before the frozen run.
- `bundle_audit_pass_rate`: bundles passing `semscrape evidence audit` divided by submitted bundles.

Always print denominators next to percentages. A false-positive rate without `fields_attempted` and extracted-count denominators is not sufficient for promotion decisions.

## Privacy Rules

The cohort remains local-first:

- Evidence is recorded in each user's local SQLite evidence DB.
- Shared bundles should use `--privacy features-only` by default.
- Redacted bundles may be used only when the participant understands what is included and the maintainer needs more context.
- Raw HTML, selectors, full candidate text, and raw values must not be uploaded or shared unless the participant explicitly opts in for that project.
- Private pages, authenticated pages, customer data, and personal data should stay local unless the participant has reviewed and approved each artifact.
- Every submitted bundle must pass `semscrape evidence audit` before it is used in cohort metrics.

Features-only evidence is enough for aggregate safety, recall, abstention, and privacy accounting. When raw HTML is needed for remediation, request a minimized repro or a private opt-in artifact after the cohort has been closed.

## Promotion Gate

Privacy is a precondition: bundle audit pass rate must be 100%, or failed bundles must be excluded and reported separately.

Promotion decisions must then prioritize extraction safety:

1. False-positive safety first: do not promote if aggregate false-positive rate exceeds 2%, if any high-severity false positive is unexplained, or if a repeated false-positive family lacks a reviewed hard-negative artifact.
2. Coverage second: only evaluate coverage after privacy and false-positive gates pass. More coverage is not useful if it comes from unsafe accepts.
3. Candidate recall explains the coverage result: do not promote when missing candidates explain a material share of failures; fix candidate generation before loosening ranker thresholds.
4. Training boundary always applies: do not use unverified production positives as training labels. Accepted outside-user outputs stay telemetry unless separately verified by user correction, benchmark expectation, manual review, or oracle-backed source.

A cohort can pass safety and still fail usability because coverage is too low. A cohort can also produce valuable hard negatives while blocking promotion.

## Post-Run Process

After all frozen runs are complete:

1. Audit all bundles and write the aggregate summary.
2. Label every failure after the run, including false positives, candidate recall misses, recoverable abstentions, spec ambiguities, normalization mismatches, and privacy issues.
3. Write an incident report for each promotion-blocking family.
4. Convert reviewed false positives into gold hard negatives only when the label is clear and the row is eligible for training.
5. Keep sealed holdout and adversarial rows out of training exports.
6. Remediate on a new branch or commit after the incident report is written.
7. Rerun regression suites, accumulated incident repros, and sealed holdouts.
8. If remediation changes behavior, run a fresh mini-holdout or a new outside-user cohort on a new frozen target. Do not overwrite the original cohort result.

The final public statement should say what was run, what failed or passed, and what remains pending. It should not describe the true outside-user cohort as complete until audited cohort artifacts and the aggregate report exist.
