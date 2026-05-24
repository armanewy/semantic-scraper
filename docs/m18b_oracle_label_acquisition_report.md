# M18B Oracle Label Acquisition Report

Status: passed.

Question: Can semscrape generate many more gold/silver labels from trusted or oracle-backed sources without using raw extraction guesses as positives?

Implemented:

```text
- expected_mode: oracle in source registries.
- semscrape oracle resolve.
- semscrape oracle report.
- alpha run --resolve-oracles.
- oracle-backed expected values injected into replay specs before canary/evidence capture.
- oracle-training-eligible-evidence.jsonl from gold/silver oracle labels only.
- oracle types: manual_expected, pypi_json, npm_registry, github_repo, json_ld.
```

Oracle scale run:

```text
registry: runs/m18b/oracle-registry.yml
oracle expected: runs/m18b/oracle-expected.jsonl
oracle report: runs/m18b/oracle-label-yield.md
alpha output: runs/auto/m18b
```

Oracle resolution:

```text
sources_with_oracle: 25
fields_resolved:    98
fields_missing:     0
gold_labels:        98
silver_labels:      0
oracle_type:        manual_expected
split:              train_candidate
```

Alpha run with oracle expected values:

```text
sources:                  25
fields_attempted:         98
coverage_rate:            0.724490
false_positive_rate:      0.000000
candidate_recall@40:      1.000000
bundle_audit_pass_rate:   1.000000
oracle_training_eligible_rows: 98
```

Safety result:

```text
Raw extraction outputs were not promoted to positives.
Oracle values were injected as expected values before evaluation.
Features-only bundle audit passed.
Training-eligible oracle export contains only train_candidate split rows with gold/silver oracle labels.
No ranker or pack was trained or promoted.
```

Decision:

```text
M18B unblocks M19 label volume: 98 oracle-backed training-eligible evidence rows exist.
M19 can attempt an evidence-driven ranker/pack update, but promotion must still require release-check against base, adversarial, external, and harvester suites.
```

