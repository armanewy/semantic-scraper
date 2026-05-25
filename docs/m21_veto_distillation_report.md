# M21 Veto Distillation and Must-Keep Calibration

Status: completed as a calibration/distillation milestone.

## Question

Can semscrape preserve the safety-veto false-positive reduction while reducing unnecessary vetoes on known-good rows?

## Inputs

- Baseline policy: `ranker-local-safe`
- Broad veto policy: `ranker-local-safe-veto`
- Baseline ranker: `models/candidate-ranker-v3.json`
- Veto ranker: `models/candidate-ranker-vNext.json`
- Calibration suites: base holdout, adversarial holdout, OOD holdout, repro minimized, harvester holdout sources, full harvester-scale run, oracle eval
- Must-keep set: `data/regression/must_keep_positives.jsonl`
- Must-veto set: `data/regression/must_veto_negatives.jsonl`

## Veto Incident Summary

M20P showed the broad veto had a useful safety signal but was too blunt:

| category | count |
|---|---:|
| aggregate vetoes | 66 |
| true veto positives | 2 |
| aggregate known-correct vetoes | 64 |
| unique new known-correct vetoes | 48 |
| unique must-veto negatives | 2 |

The 48 unique known-correct vetoes were added to `must_keep_positives.jsonl`, raising the must-keep set from 6 to 54 rows. The two true veto positives were added to `must_veto_negatives.jsonl`.

Top known-correct veto families:

| field | count |
|---|---:|
| first_product_title | 13 |
| first_tag | 10 |
| second_product_price | 5 |
| first_product_price | 5 |
| second_product_title | 4 |
| first_quote_tag | 3 |

Known-correct vetoes by source group:

| group | count |
|---|---:|
| ecommerce | 12 |
| ecommerce_books | 12 |
| article_quotes | 8 |
| article | 6 |
| docs | 4 |
| listings | 3 |
| docs_django | 2 |
| reference_iana | 1 |

The broad veto is mostly rejecting legitimate product/list/tag/text extractions, not just hard traps.

## Threshold Calibration

Command:

```bash
semscrape ranker veto-calibrate \
  --suite 'base=runs/m20p/base-baseline.jsonl=>runs/m20p/base-veto.jsonl' \
  --suite 'adversarial=runs/m20p/adversarial-baseline.jsonl=>runs/m20p/adversarial-veto.jsonl' \
  --suite 'ood_holdout=runs/m20p/ood-holdout-baseline.jsonl=>runs/m20p/ood-holdout-veto.jsonl' \
  --suite 'repro_minimized=runs/m20p/repro-baseline.jsonl=>runs/m20p/repro-veto.jsonl' \
  --suite 'holdout_sources=runs/m20p/holdout-sources-baseline.jsonl=>runs/m20p/holdout-sources-veto.jsonl' \
  --suite 'harvester_scale=runs/m20p/harvester-baseline.jsonl=>runs/m20p/harvester-veto.jsonl' \
  --suite 'oracle_eval=runs/m20p/oracle-baseline.jsonl=>runs/m20p/oracle-veto.jsonl' \
  --must-keep data/regression/must_keep_positives.jsonl \
  --must-veto data/regression/must_veto_negatives.jsonl \
  --threshold 0.05 0.08 0.10 0.20 0.30 0.34 0.35 0.40 0.50 0.60 \
  --out runs/m21/veto-calibration.jsonl \
  --summary-out runs/m21/veto-calibration.md
```

Result: no broad confidence threshold passed.

| threshold | coverage | FPR | coverage loss | vetoes | saved FPs | known-correct vetoes | must-keep veto rate | must-veto block rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.050 | 0.616344 | 0.004155 | 0.023545 | 17 | 0 | 17 | 0.242857 | 0.000000 |
| 0.080 | 0.613573 | 0.002770 | 0.026315 | 19 | 1 | 18 | 0.257143 | 0.500000 |
| 0.340 | 0.566482 | 0.001385 | 0.073407 | 53 | 2 | 51 | 0.728571 | 1.000000 |
| 0.600 | 0.548476 | 0.001385 | 0.091413 | 66 | 2 | 64 | 0.914286 | 1.000000 |

Lowering the broad threshold cannot preserve both safety and coverage. It either misses must-veto rows or still vetoes too many known-good rows.

## Trap-Only Evaluation

The two true veto positives both came from the `first_content_link` field family. A narrow field-specific trap-only simulation was evaluated:

```bash
semscrape ranker veto-calibrate \
  --suite ... \
  --must-keep data/regression/must_keep_positives.jsonl \
  --must-veto data/regression/must_veto_negatives.jsonl \
  --threshold 0.0 \
  --field-threshold first_content_link=0.34 \
  --max-suite-coverage-loss 0.10 \
  --out runs/m21/veto-lite-calibration.jsonl \
  --summary-out runs/m21/veto-lite-calibration.md
```

Result:

| metric | value |
|---|---:|
| baseline coverage | 0.639889 |
| trap-only coverage | 0.635734 |
| coverage loss | 0.004155 |
| baseline FPR | 0.004155 |
| trap-only FPR | 0.001385 |
| recall@40 | 0.987498 |
| veto count | 3 |
| true veto positives | 2 |
| known-correct vetoes | 1 |
| must-keep veto rate | 0.014286 |
| must-veto block rate | 1.000000 |

This is a useful internal trap-detector shape, but it is narrow and based on only two true veto positives.

## Decision

Do not promote the broad `ranker-local-safe-veto` policy.

Do not change public/default behavior:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

The broad veto remains internal/opt-in. The distilled trap-only result is promising enough to keep as an internal calibration candidate, but it should not become a public policy until it is implemented as explicit high-precision trap rules and validated on a fresh holdout.

## Next Work

- Convert trap-only behavior into explicit interpretable veto rules only if more `first_content_link`/link-trap evidence supports it.
- Add more must-veto negatives from reviewed false positives rather than relying on two oracle rows.
- Keep using `must_keep_positives.jsonl` and `must_veto_negatives.jsonl` in future veto/ranker calibration.
- Proceed to outside-user validation on the unchanged default if product usability is the priority.
