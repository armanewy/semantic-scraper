# M22: Trap-Only Veto Promotion Trial

## Question

Can the high-precision trap-only veto reduce false positives with negligible coverage loss?

## What changed

M21 showed that the broad learned safety veto reduced false positives but vetoed too many known-correct rows. M22 turns the narrow, calibrated part of that result into an explicit trap-only mode.

Implemented pieces:

- `ranker-local-safe-trap-veto` policy.
- `trap_only_veto_event(...)` with reason-coded trap decisions.
- Learned field-specific threshold support for the `first_content_link` trap, defaulting to the M21-calibrated `0.34` threshold.
- Deterministic high-precision trap vetoes for:
  - first content link ordinal mistakes;
  - updated-date candidates when a published date is requested;
  - tag-cloud / related / recommended title traps;
  - shipping/add-on price traps;
  - table-context mismatch traps.
- `semscrape ranker trap-veto-report` for promotion-readiness reporting across baseline vs trap-veto JSONL suites.
- Regression tests for low-confidence first-content-link vetoes, high-confidence passes, ordinal traps, no-op safe titles, and interpretable tag-cloud veto reasons.

## Runtime Behavior

The trap-only policy is blocking-only:

```text
ranker-local-safe accepts candidate
  -> run trap-only veto checks
  -> if high-precision trap fires, abstain
  -> otherwise keep accepted value
```

It never chooses a replacement candidate.

## Example

```bash
semscrape canary corpus/repro_minimized/manifest.yml \
  --policy ranker-local-safe-trap-veto \
  --ranker models/candidate-ranker-v3.json \
  --veto-ranker models/candidate-ranker-vNext.json \
  --veto-confidence-below 0.34 \
  --out runs/m22/trap-veto.jsonl
```

Compare with baseline:

```bash
semscrape ranker trap-veto-report \
  --suite 'repro=runs/m22/baseline.jsonl=>runs/m22/trap-veto.jsonl' \
  --out runs/m22/trap-veto-report.md
```

## Promotion Gates

Trap-only veto should only be promoted if it passes the accumulated-suite gate:

```text
FPR <= baseline FPR on every suite
adversarial FPR remains 0
aggregate coverage loss <= 1%
no critical suite loses >3% coverage
known-correct vetoes <= 3
every veto has an interpretable reason code
```

## Status

Tooling and policy implementation are complete. Promotion still requires running the accumulated-suite comparison and a fresh mini-holdout.

## Notes

This mode is intentionally separate from the broad `ranker-local-safe-veto` policy. The broad veto remains internal/opt-in because M20P/M21 showed it reduced false positives at the cost of unacceptable coverage loss.
