# candidate-ranker-v3.json

## Summary

- type: `semscrape_candidate_ranker`
- schema_version: `1`
- feature_schema_version: `1`
- feature_count: `42`
- threshold: `0.7`
- margin: `0.0`

## Training Metadata

- hard_negatives: `399`
- kind: `centroid-delta`
- negative_weight: `3281.0`
- negatives: `1286`
- positive_weight: `1450.0`
- positives: `145`
- rows: `1431`
- trained_at: `1779566733`

## Training Data

- path: `data/candidate-ranking-v3.jsonl`
- rows: `1431`
- positives: `145`
- hard_negatives: `399`
- categories: `articles, docs, ecommerce, events, listings, pricing_tables`
- field_types: `date, number, price, text`

## Metrics

- m10_adversarial_holdout_false_positive_rate: `0.0`
- m10_base_holdout_candidate_recall_at_40: `1.0`
- m10_base_holdout_coverage: `1.0`
- m10_base_holdout_false_positive_rate: `0.0`
- m10_release_check_passed: `True`
- m10_training_hard_negatives: `399`
- m10_training_positives: `145`
- m10_training_rows: `1431`

## Evaluation Runs

| run | rows | candidate recall | coverage | false positive | model call |
|---|---:|---:|---:|---:|---:|
| base_holdout | 20 | 1.000 | 1.000 | 0.000 | 0.000 |
| adversarial_holdout | 6 | 0.000 | 0.000 | 0.000 | 0.000 |

## Evidence Policy

- privacy_mode: `features-only`
- excluded: base_holdout and adversarial_holdout sealed evaluation cases
- excluded: bronze and untrusted production outputs

## Known Limits

- Initial release-candidate corpus is replay-only and intentionally small.
- Metrics describe the replay suites recorded in this repo, not arbitrary web pages.
- Abstention is an intended safety behavior outside the demonstrated domain envelope.
- Untrusted production evidence should not be used as positive training data.
