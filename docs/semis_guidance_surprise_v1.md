# semis_guidance_surprise_v1

## Result From Agent 1

Agent 1 falsified the broad label-free strategy:

```text
Trade semiconductor earnings events.
```

The reviewed corpus is still valuable because it provides SEC-sourced event provenance:

```text
294 SEC Item 2.02 earnings events
294 usable event-study rows
timestamp coverage
source provenance
```

The missing layer is expectation surprise. An Item 2.02 event says that an earnings release occurred; it does not say whether the result was better or worse than investor expectations.

## Next Research Question

For semiconductor earnings events with known EPS, revenue, and guidance surprise, do forward guidance surprises predict 1-day or 3-day abnormal returns after adjusting for SMH/SPY, pre-event run-up, and implied move?

## Base Corpus

Start from:

```text
runs/semis_earnings_reviewed_v1/data/events/05_curated_corpus.csv
```

Do not target full coverage. Target a smaller reviewed subset:

```text
80-150 high-quality labeled rows
```

## Required Labels

Each reviewed event should include:

```text
event_id
ticker
event_time
release_session
actual_eps
consensus_eps
eps_surprise_pct
actual_revenue
consensus_revenue
revenue_surprise_pct
guidance_revenue_mid
consensus_forward_revenue
guidance_revenue_surprise_pct
surprise_direction
surprise_magnitude
```

Nice-to-have fields:

```text
actual_gross_margin
consensus_gross_margin
gross_margin_surprise_pct
guidance_gross_margin_mid
consensus_forward_gross_margin
guidance_gross_margin_surprise_pct
implied_move_pct
analyst_count
analyst_revision_count_7d
analyst_revision_mean_30d
```

## Labeling Rules

Do not derive labels from post-event stock movement.

Compute expectation deltas from pre-event expectations:

```text
eps_surprise_pct = (actual_eps - consensus_eps) / abs(consensus_eps)

revenue_surprise_pct = (actual_revenue - consensus_revenue) / abs(consensus_revenue)

guidance_revenue_surprise_pct =
    (guidance_revenue_mid - consensus_forward_revenue)
    / abs(consensus_forward_revenue)
```

Initial direction rules:

```text
positive:
  guidance_revenue_surprise_pct >= 0.02
  OR revenue_surprise_pct >= 0.02 and guidance is non-negative

negative:
  guidance_revenue_surprise_pct <= -0.02
  OR revenue_surprise_pct <= -0.02
  OR gross-margin or guidance miss is material

mixed:
  EPS/revenue beat but guidance misses
  OR revenue beats but margin/guidance disappoints

neutral:
  all major surprises are within a small band
```

Suggested score:

```text
fundamental_surprise_score =
  0.15 * eps_surprise_z
+ 0.25 * revenue_surprise_z
+ 0.40 * guidance_revenue_surprise_z
+ 0.20 * gross_margin_or_guidance_margin_surprise_z
```

## Tests

### 1. Negative Guidance After Pre-Event Run-Up

Hypothesis: if a semiconductor stock runs up before earnings and then forward revenue guidance misses, the market punishes it more strongly.

Filter:

```text
market_adjusted_pre_return_20d > 0
guidance_revenue_surprise_pct < -0.02
```

Primary horizon:

```text
h1 and h3 sector-adjusted abnormal return
```

### 2. Gross-Margin Disappointment

Hypothesis: margin disappointment matters more than headline EPS, especially for equipment and analog names.

Filter:

```text
gross_margin_surprise_pct < 0
OR guidance_gross_margin_surprise_pct < 0
```

Segments:

```text
equipment: AMAT, LRCX, KLAC
analog/mixed-signal: TXN, ADI, MCHP, ON
```

### 3. AI/Data-Center Guidance Beat

Hypothesis: AI-exposed names with data-center or accelerator guidance beats produce stronger positive abnormal returns than generic EPS beats.

Universe:

```text
NVDA, AMD, AVGO, MRVL, MU
```

Features:

```text
data_center_revenue_growth
ai_or_accelerator_mentions
forward_revenue_guidance_surprise_pct
capex_or_supply_constraint_commentary
```

### 4. Equipment-Company Guidance Cuts

Hypothesis: semiconductor equipment companies react predictably to forward guidance cuts because they are tightly linked to wafer-fab-equipment cycle expectations.

Universe:

```text
AMAT, LRCX, KLAC
```

Primary feature:

```text
guidance_revenue_surprise_pct
```

## Report Requirements

For each test, report:

```text
event count
abnormal return base rates
walk-forward result
calibration
placebo result
peer-control result
null-shuffle result
costs/slippage impact
verdict: continue, narrow, kill, or inconclusive
```

## Graduation Gates

Do not graduate the run unless it passes:

```text
>= 80 reviewed labeled events
>= 40 events with guidance surprise fields
>= 30 out-of-sample predictions
< 20% unknown surprise_direction
< 20% unknown surprise_magnitude
exact or confidently inferred release_session for nearly all rows
placebo result meaningfully weaker than real result
peer-control result weaker than real result
null-shuffle p-value <= 0.10
calibration ECE <= 0.20
positive net result after costs/slippage
```

The most important gate is label quality. If label quality is weak, any apparent signal is likely not usable.
