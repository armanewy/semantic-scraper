# Safety Veto Promotion Readiness

Decision: `keep_opt_in_internal`.
Passed: `false`.

## Aggregate

- suites: `7`
- rows: `722`
- baseline_coverage_rate: `0.639889`
- veto_coverage_rate: `0.548476`
- coverage_loss: `0.091413`
- baseline_false_positive_rate: `0.004155`
- veto_false_positive_rate: `0.001385`
- baseline_candidate_recall_at_k: `0.987498`
- veto_candidate_recall_at_k: `0.987498`
- veto_count: `66`
- veto_true_positive_count: `2`
- veto_false_positive_count: `64`
- coverage_lost_to_veto: `64`
- oracle_false_positives_prevented: `2`
- must_keep_positive_veto_rate: `0.000000`

## Gates

| gate | passed |
|---|---:|
| fpr_not_regressed_everywhere | true |
| adversarial_fpr_zero | true |
| oracle_fpr_improved_or_equal | true |
| total_coverage_loss_within_limit | false |
| suite_coverage_loss_within_limit | false |
| must_keep_positive_veto_rate_within_limit | true |
| candidate_recall_not_regressed | true |
| veto_reason_codes_present | true |

## Suites

| suite | rows | baseline coverage | veto coverage | coverage loss | baseline FPR | veto FPR | baseline recall@40 | veto recall@40 | vetoes | saved FPs | lost TPs | must-keep veto rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 20 | 0.450000 | 0.450000 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 1.000000 | 0 | 0 | 0 | 0.000000 |
| adversarial | 6 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0.000000 |
| ood_holdout | 26 | 0.346154 | 0.346154 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 1.000000 | 0 | 0 | 0 | 0.000000 |
| repro_minimized | 70 | 0.585714 | 0.585714 | 0.000000 | 0.000000 | 0.000000 | 1.000000 | 1.000000 | 0 | 0 | 0 | 0.000000 |
| holdout_sources | 105 | 0.647619 | 0.495238 | 0.152381 | 0.000000 | 0.000000 | 0.990476 | 0.990476 | 16 | 0 | 16 | 0.000000 |
| harvester_scale | 464 | 0.678879 | 0.577586 | 0.101293 | 0.002155 | 0.002155 | 0.995633 | 0.995633 | 47 | 0 | 47 | 0.000000 |
| oracle_eval | 31 | 0.645161 | 0.548387 | 0.096774 | 0.064516 | 0.000000 | 1.000000 | 1.000000 | 3 | 2 | 1 | 0.000000 |

## Interpretation

- `veto_true_positive_count` counts baseline false positives blocked by the veto.
- `veto_false_positive_count` counts known-correct baseline extractions blocked by the veto.
- This report evaluates promotion readiness only; it does not export labels or train models.
