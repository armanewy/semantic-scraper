# Evidence Intake Runbook

This runbook is for maintainers reviewing public-alpha evidence bundles.

## Principles

- Reject unsafe bundles before reading them into training data.
- Treat false positives as the highest-priority incidents.
- Do not train on unverified accepted outputs as positive labels.
- Preserve sealed holdouts for release checks.
- Promote a ranker or pack only when false-positive safety does not regress.

## Intake Steps

Audit every bundle:

```bash
semscrape evidence audit bundles/project-001.zip
```

Accept only bundles with:

```text
ok: true
raw_html_present: false
full_candidate_text_present: false
selector_present: false
value_text_present: false
```

Merge accepted bundles:

```bash
semscrape evidence intake bundles/*.zip \
  --out data/intake/public-alpha-evidence.jsonl
```

Summarize the alpha cohort:

```bash
semscrape alpha summarize bundles/*.zip \
  --out runs/m16/public-alpha-summary.md
```

## Label Trust

Use these trust levels:

```text
gold:
  explicit user correction
  benchmark/canary expected value
  manually reviewed false positive or hard negative

silver:
  confirmed fallback recovery in benchmark/canary
  repeated validated selector hit in canary

bronze:
  high-confidence production extraction without ground truth

untrusted:
  unknown production output
```

Training exports for base/domain rankers should default to `gold` and selected `silver`. Bronze/untrusted positives are local/project-tuning evidence only unless manually reviewed.

## False Positive Triage

For every false positive, record:

```text
field name
expected value
actual value
policy
ranker version
candidate_recall@40
selected candidate region
expected candidate region
validator reasons/penalties
ranker confidence/margin
failure type
label action
```

Failure types:

```text
semantic_false_positive
region_confusion
validator_too_permissive
ranker_overconfident
spec_ambiguity
normalization_mismatch
candidate_missing
```

True semantic false positives become gold hard negatives. Spec ambiguities and normalization mismatches should not be blindly used as semantic negatives.

## Pack/Ranker Update

Build a candidate pack or ranker only from trusted evidence:

```bash
semscrape pack gaps data/intake/public-alpha-evidence.jsonl \
  --pack ecommerce \
  --out runs/m16/ecommerce-gaps.md
```

Release-check before promotion:

```bash
semscrape pack release-check packs/ecommerce-v2-candidate \
  --baseline packs/ecommerce-v1 \
  --out runs/m16/ecommerce-v2-release-check.json
```

Promotion is blocked if:

- false-positive rate regresses
- adversarial false-positive rate is nonzero
- feature schema is incompatible
- model card is missing
- candidate coverage improves only by accepting unsafe candidates

No promotion is a valid outcome when evidence is useful but not yet safe enough.
