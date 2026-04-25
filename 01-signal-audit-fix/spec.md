# Split 01 — Signal Audit & Fix

## Goal

Make the signal pipeline correct. Before running any backtest, the core logic that decides when and in which direction to enter a butterfly must be demonstrably correct and unit-tested.

## Context

**Strategy doc:** `/Volumes/One Touch/NSE/onesec/curvex/eSSVI Butterfly Stat-Arb Strategy.md`
*(Note: the doc contains some imprecise language — use the math as ground truth over prose descriptions.)*

**Package root:** `/Volumes/One Touch/NSE/onesec/curvex/src/essvi_bfly/`

**Relevant modules for this split:**
- `signal/candidate_selection.py` — butterfly direction assignment and edge calculation ← primary suspect
- `signal/zscores.py` — rolling z-score and persistence counter
- `signal/residuals.py` — market IV computation and eSSVI residual
- `surface/calibrate.py` — calibration correctness is a prerequisite (brief audit only)
- `iv/implied_vol.py` — IV solver (brief audit only; Newton+Brent fallback)

## The Core Problem

The residual is defined as: `residual_iv = iv_market - iv_essvi`

- Positive residual (z > 0): body strike's market IV is **above** eSSVI → body option is **overpriced** relative to the model
- Negative residual (z < 0): body strike's market IV is **below** eSSVI → body option is **underpriced**

**Butterfly economics:**
- A long butterfly (buy 1 wing-low, sell 2 body, buy 1 wing-high) profits when body IV falls back to fair value (sell the overpriced body)
- A short butterfly (sell 1 wing-low, buy 2 body, sell 1 wing-high) profits when body IV rises back to fair value (buy the underpriced body)

**Mapping:**
- z > +threshold → body overpriced → **LONG butterfly** (sell the body, buy wings)
- z < −threshold → body underpriced → **SHORT butterfly** (buy the body, sell wings)

In `candidate_selection.py` (line `if body["zscore"] < 0:`), the code currently assigns `SHORT_BFLY` when z < 0. Verify whether this matches the above convention given the `_build_actions` definition in `engine.py` (LONG_BFLY = BUY low, SELL body×2, BUY high).

## Tasks

### 1. Direction Convention Audit

Read `candidate_selection.py` and `engine.py._build_actions` together. Determine:
- Is `LONG_BFLY` in the code "buy wings, sell body" (standard) or "buy body, sell wings" (non-standard)?
- Does the z-score → direction mapping correctly assign trades that profit from mean reversion?
- Document the verdict (correct or needs fix) with a 3-line comment at the top of `candidate_selection.py`

Fix the direction assignment if it is wrong.

### 2. Edge Calculation Audit

The edge for a butterfly entry is the dollar difference between the model-fair butterfly premium and the market butterfly premium, in the direction that profits from mean reversion:

- LONG_BFLY entry: we BUY the butterfly at `market_premium` (cost) vs model says it's worth `model_premium`. Edge = `model_premium - market_premium` (positive when model > market, i.e., structure is cheap).
- SHORT_BFLY entry: we SELL the butterfly at `market_premium` (receipt) vs model says it's worth `model_premium`. Edge = `market_premium - model_premium` (positive when market > model, i.e., structure is expensive).

Verify the edge formula in `candidate_selection.py` matches this and fix if not.

### 3. Z-Score Rolling Window — Session Boundary

In `zscores.py`, the rolling z-score is computed per `contract_name` over `zscore_window_5m = 75` bars. At 5-min frequency, 75 bars = 6.25 hours, which spans overnight into the previous trading session. This contaminates the z-score at session open with stale data.

Fix: Group or reset the rolling computation at each session boundary. Options:
- Add a `session_date` column and compute rolling stats within-session only
- Or clip to the valid intraday range before computing (9:15–15:30 IST per session)

Confirm that `min_periods` is set appropriately so early-session bars with insufficient history are marked as NaN (filtered out by `same_sign_persistence < persistence_bars`).

### 4. Persistence Counter Verification

In `zscores.py`, the `persistence` function counts consecutive bars with the same z-score sign. Verify:
- The counter correctly resets to 0 (not 1) when the sign flips or is zero
- The counter increments from 1 on the first bar of a new run (not from 0)
- `same_sign_persistence >= config.persistence_bars` (currently 2) means the signal held for at least 2 full bars before triggering

Add a simple hand-traced test case to verify.

### 5. Unit Tests

Write `tests/test_signal.py` with at minimum:

- `test_direction_long_bfly`: given a positive z-score at body, assert direction = LONG_BFLY
- `test_direction_short_bfly`: given a negative z-score at body, assert direction = SHORT_BFLY
- `test_edge_long_bfly_positive`: LONG_BFLY edge is positive when market_premium < model_premium
- `test_edge_short_bfly_positive`: SHORT_BFLY edge is positive when market_premium > model_premium
- `test_persistence_counter`: hand-trace a 6-element z-score sequence with one sign flip, assert persistence values
- `test_zscore_rolling_within_session`: verify z-score is NaN for the first `min_periods` bars of a session after the session-boundary fix

## What This Split Does NOT Cover

- Backtest engine execution logic (split 02)
- End-to-end data pipeline (split 02)
- Performance analysis (split 03)

## Outputs / Deliverables

1. Corrected `signal/candidate_selection.py` with direction fix and edge fix (if needed)
2. Corrected `signal/zscores.py` with session-boundary-aware rolling window
3. `tests/test_signal.py` with all 6 test cases passing

## Dependencies

- Reads from: `src/essvi_bfly/signal/`, `src/essvi_bfly/backtest/engine.py` (for `_build_actions` reference)
- Does not require data or a running backtest
- Provides: corrected signal module consumed by split 02
