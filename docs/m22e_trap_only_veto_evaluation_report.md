# M22E: Trap-Only Veto Evaluation

Status: executed; promotion blocked.

Question: Does `ranker-local-safe-trap-veto` reduce false positives with negligible coverage loss across the accumulated suites and a fresh mini-holdout?

## Decision

Do not promote `ranker-local-safe-trap-veto`.

Keep defaults unchanged:

```text
candidate-ranker-v3
packs/ecommerce-v1
ranker-local-safe
```

The trap-only policy stayed safe in the narrow sense: it did not increase false positives, adversarial FPR remained zero, candidate recall did not regress, every veto had a reason code, and the two M21 must-veto rows were blocked. It did not reduce observed false positives in this evaluation, and it vetoed four known-correct rows.

## Aggregate Results

```text
suites:                         11
rows:                           1093
baseline_coverage_rate:         0.667886
trap_veto_coverage_rate:        0.664227
coverage_loss:                  0.003660
baseline_false_positive_rate:   0.004574
trap_veto_false_positive_rate:  0.004574
baseline_candidate_recall@40:   0.988997
trap_veto_candidate_recall@40:  0.988997
veto_count:                     4
true_veto_positive_count:       0
known_correct_vetoes:           4
false_positives_prevented:      0
must_keep_positive_veto_rate:   0.000000
must_veto_block_rate:           1.000000
```

## Failed Gates

```text
suite_coverage_loss_within_limit: false
known_correct_vetoes_within_limit: false
```

The largest regression was `original_external`, where coverage dropped from `0.800000` to `0.666667` because two `trap_shipping_or_addon_price` vetoes blocked known-correct rows while preserving the same false-positive rate.

The harvester suite also lost two known-correct rows with no false-positive reduction:

```text
harvester baseline coverage:   0.678879
harvester trap coverage:       0.674569
harvester baseline FPR:        0.002155
harvester trap FPR:            0.002155
```

## Passing Gates

```text
fpr_not_regressed_everywhere: true
adversarial_fpr_zero: true
total_coverage_loss_within_limit: true
must_keep_positive_veto_rate_within_limit: true
must_veto_block_rate_within_limit: true
candidate_recall_not_regressed: true
veto_reason_codes_present: true
```

## Artifacts

```text
runs/m22e/trap-veto-promotion-report.md
runs/m22e/trap-veto-promotion-report.json
```

## Interpretation

The M22 trap-only policy is safer than the broad learned veto, but it is still not useful enough to promote. It currently behaves as a narrow diagnostic layer that can block known trap families, but the observed promotion-trial value was not positive: no false positives were prevented, while known-correct rows were vetoed.

Next work should either narrow `trap_shipping_or_addon_price` with additional must-keep calibration, or leave trap-veto as an internal diagnostic and continue with outside-user validation on the unchanged default policy.
