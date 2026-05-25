# Policies

Policies are named presets for strictness, local ranker use, and local LLM fallback. The CLI applies them with `--policy`.

Use `ranker-local-safe` for public-alpha or high-precision workflows where abstention is preferable to a wrong value.

## Summary

| Policy | LLM | Ranker | Strict gate | Best use |
| --- | --- | --- | --- | --- |
| `conservative` | no | no | yes | deterministic baseline and debugging |
| `safe-local` | local Ollama after abstention | no | yes | local model recovery without ranker |
| `ranker-local` | no | yes | yes | offline ranker coverage experiments |
| `ranker-local-safe` | no | yes | yes, tighter | public-alpha and high-precision runs |
| `ranker-plus-llm` | local Ollama after recoverable ranker abstention | yes | yes | measured local fallback experiments |
| `aggressive` | yes | no | no | manual exploratory debugging only |

The CLI also contains internal opt-in veto policies, `ranker-local-safe-veto` and `ranker-local-safe-trap-veto`. They are blocking-only evaluation policies and are not the recommended public-alpha default.

## `conservative`

`conservative` uses deterministic heuristic ranking and strict gates. It does not call an LLM and does not use the candidate ranker.

Use it when:

- you want the smallest deterministic baseline
- you are debugging validators, candidates, or strict gate behavior
- you want no model dependency of any kind

Tradeoff: it can abstain or miss recoverable cases because there is no ranker or model repair step.

## `safe-local`

`safe-local` keeps strict heuristic gates and enables local Ollama fallback after heuristic abstention. Model choices must still pass validation and strict gates before they can be learned.

Use it when:

- you have a local Ollama daemon available
- you want a model to choose among bounded DOM candidates after deterministic abstention
- you are experimenting with model recovery on pages where a ranker is not configured

Tradeoff: it can call the model more broadly than `ranker-plus-llm` because its fallback policy is `all`.

## `ranker-local`

`ranker-local` uses the packaged offline ranker, or a ranker supplied with `--ranker`, after the strict heuristic path abstains. It does not use an LLM. It allows one ranker penalty by default.

Use it when:

- you want offline extraction with the local ranker but no LLM calls
- you are comparing rankers or measuring coverage
- you are running internal experiments where more coverage is useful

Tradeoff: it is less conservative than `ranker-local-safe`, so it is not the best default when false positives matter most.

## `ranker-local-safe`

`ranker-local-safe` is the recommended public-alpha policy. It uses the local ranker without LLM calls and tightens acceptance thresholds:

- higher heuristic confidence and margin
- higher validator confidence
- high ranker confidence
- nonzero ranker margin
- zero allowed ranker penalties
- field-specific safety gates

Use it when:

- you are running public-alpha, pilot, canary, or high-precision extraction
- a missing value is acceptable but a silent wrong value is not
- you are collecting evidence for review or future ranker/pack work

Expected behavior:

```text
strong evidence: extract
ambiguous evidence: abstain
missing candidates: abstain
unsafe region/trap: abstain
```

Tradeoff: low coverage with clear abstention reason codes is expected on unfamiliar templates.

## `ranker-plus-llm`

`ranker-plus-llm` first uses the strict heuristic path, then the local ranker, and only calls the local LLM for recoverable ranker abstentions by default. Its default LLM fallback policy is `recoverable-only`.

Use it when:

- you want to measure whether local Ollama improves recovery after safe ranker abstention
- you can tolerate local model latency
- you want model calls to stay bounded by ranker and fallback gates

Tradeoff: unsafe ranker reasons suppress the LLM instead of asking it to override safety. This is intentional.

Example:

```bash
semscrape extract spec.yml inputs/example.html \
  --policy ranker-plus-llm \
  --model qwen3:1.7b
```

## `aggressive`

`aggressive` disables strict extraction and enables local model use without waiting for abstention. It lowers confidence and validator thresholds.

Use it only when:

- you are debugging candidate lists or model behavior
- you explicitly prefer exploratory coverage over safety
- results will be manually reviewed and not treated as trusted labels

Do not use it for public-alpha, unattended automation, training labels, or high-precision extraction.

## Choosing A Policy

- Public alpha or high precision: `ranker-local-safe`
- Offline ranker comparison: `ranker-local`
- Deterministic baseline: `conservative`
- Local LLM recovery experiment: `ranker-plus-llm`
- Local model without ranker: `safe-local`
- Manual exploratory debugging: `aggressive`

For scripts, pair the policy with required-field gates such as `--require-fields`, `--fail-on-abstain`, and `--min-coverage` so abstentions are visible to the caller.
