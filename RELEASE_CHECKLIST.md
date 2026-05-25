# Release Checklist

Use this checklist for alpha releases.

## Required Checks

```bash
python -m pip install -e ".[dev]"
python scripts/check_release_consistency.py
python -m ruff check .
python -m pytest -q
semscrape doctor
semscrape ranker info
semscrape extract examples/product.yml examples/product_v2.html --policy ranker-local --values-only
semscrape canary corpus/ood_holdout/manifest.yml --policy ranker-local --out runs/release-ood-holdout.jsonl
```

## Artifact Checks

- Packaged ranker exists at `src/semscrape/assets/candidate-ranker-v3.json`.
- `semscrape ranker info` reports the expected schema and metrics.
- The default offline extraction path does not require Ollama.
- Optional `ranker-plus-llm` documentation still names `qwen3:1.7b` as optional.

## Documentation Checks

- README quickstart works from a fresh clone.
- `MILESTONES.md` reflects the current milestone state.
- Any generated run outputs remain under `runs/` and are not committed.
