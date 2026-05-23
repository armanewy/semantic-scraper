# semscrape corpus layout

The M10 base-ranker workflow separates training/dev data from sealed holdouts.

```text
base_train/             training cases allowed for ranker fitting
base_dev/               development cases allowed for threshold and gate hardening
base_holdout/           sealed non-adversarial release-candidate holdout
adversarial_holdout/    sealed trap-heavy release-candidate holdout
```

Do not add `base_holdout` or `adversarial_holdout` cases to ranker training data.
Use them only for release-candidate evaluation.
