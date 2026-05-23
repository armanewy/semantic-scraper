# Local Model Bakeoff - 2026-05-23

## Setup

Ollama was installed locally on Windows and the following models were pulled:

```text
qwen3:1.7b
gemma3:1b
qwen3:4b
```

The bakeoff command was:

```powershell
python -m semscrape.cli eval-model fixtures\**\spec.yml `
  --models qwen3:1.7b gemma3:1b qwen3:4b `
  --top-k 40 `
  --strict `
  --out runs\model-strict.jsonl `
  --failures-dir runs\failures-model-strict
```

Generated run artifacts are intentionally not committed.

## Strict Bakeoff Results

| model | coverage | false positive | validated accuracy | abstention | model error | latency ms/field |
|---|---:|---:|---:|---:|---:|---:|
| gemma3:1b | 0.000 | 0.000 | 0.000 | 1.000 | 0.082 | 4059.0 |
| qwen3:1.7b | 0.590 | 0.000 | 0.600 | 0.410 | 0.049 | 7162.4 |
| qwen3:4b | 0.311 | 0.000 | 0.317 | 0.689 | 0.492 | 26596.3 |

The first pass says qwen3:1.7b is the only useful model in this matrix. It recovers coverage well above strict heuristic while preserving zero false positives on this fixture set.

## Calibration Result

Calibration was run from the captured model JSONL without additional model calls:

```powershell
python -m semscrape.cli calibrate `
  --from-jsonl runs\model-strict.jsonl `
  --out runs\model-calibration.jsonl
```

Best qwen3:1.7b configuration under `false_positive_rate <= 0.02`:

```text
min_confidence: 0.70
min_margin: 0.00
min_validator_confidence: 0.50
coverage_rate: 0.622951
false_positive_rate: 0.000000
validated_accuracy: 0.633333
abstention_rate: 0.377049
model_error_rate: 0.049180
```

This crosses the "great" target for coverage with zero observed false positives on the current fixture set.

## Comparison To Heuristic Baselines

| mode | coverage | false positive |
|---|---:|---:|
| loose heuristic | 1.000 | 0.196721 |
| fixed strict heuristic | 0.295082 | 0.000000 |
| calibrated heuristic | 0.622951 | 0.016393 |
| qwen3:1.7b strict | 0.590164 | 0.000000 |
| qwen3:1.7b calibrated | 0.622951 | 0.000000 |

The calibrated heuristic is already strong on this small corpus, but qwen3:1.7b reaches similar coverage with lower observed false positives.

## Interpretation

The architecture is still viable:

```text
strict heuristic succeeds -> return
strict heuristic abstains -> ask local model
model choice clears gates -> return
otherwise -> abstain
```

The next useful implementation step is a strict-plus-model extraction flow that calls the model only after strict heuristic abstention. The next research step is to inspect the qwen3:1.7b failure artifacts and reduce model errors/no-candidate abstentions.

## Safe-Local Runtime Policy Result

After adding the production policy flow:

```text
cache -> conservative strict heuristic -> qwen3:1.7b recovery on abstention -> strict gate -> learn accepted only
```

The fixture result was:

```text
coverage_rate: 0.606557
false_positive_rate: 0.000000
validated_accuracy: 0.616667
heuristic_accept_rate: 0.295082
heuristic_abstention_rate: 0.704918
model_call_rate: 0.704918
model_recovery_rate: 0.441860
model_validated_recovery_rate: 0.441860
model_false_positive_rate: 0.000000
model_error_rate: 0.032787
```

This meets the first safe-local gate:

```text
coverage >= 60%
false_positive_rate <= 2%
model_call_rate < 75%
```
