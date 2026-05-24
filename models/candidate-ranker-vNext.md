# candidate-ranker-vNext.json

## Summary

- type: `semscrape_candidate_ranker`
- schema_version: `1`
- feature_schema_version: `unknown`
- feature_count: `41`
- threshold: `0.7`
- margin: `0.0`

## Training Metadata

- hard_negatives: `1091`
- kind: `centroid-delta`
- negative_weight: `8004.0`
- negatives: `2549`
- positive_weight: `1310.0`
- positives: `131`
- rows: `2680`
- trained_at: `1779666021`

## Training Data

- path: `data/m19/candidate-ranking-oracle-train.jsonl`
- rows: `2680`
- positives: `131`
- hard_negatives: `1091`
- categories: `article_quotes, database_sqlite, docs_django, docs_python`
- field_types: `text`

## Evaluation Runs

| run | rows | candidate recall | coverage | false positive | model call |
|---|---:|---:|---:|---:|---:|
| oracle_eval | 31 | 1.000 | 0.548 | 0.000 | 0.000 |
| base_holdout | 20 | 1.000 | 0.150 | 0.000 | 0.000 |
| adversarial | 6 | 0.000 | 0.000 | 0.000 | 0.000 |

## Evidence Policy

- privacy_mode: `features-only`
- excluded: holdout/adversarial/monitor_only source splits

## Known Limits

- Oracle labels cover docs/article/database pages only; ecommerce pack promotion still needs more domain-specific trusted labels.
- Candidate is safer than v3 on oracle eval but loses sealed base-holdout coverage, so it is not promoted.
- Metrics describe the replay suites recorded in this repo, not arbitrary web pages.
- Abstention is an intended safety behavior outside the demonstrated domain envelope.
- Untrusted production evidence should not be used as positive training data.
