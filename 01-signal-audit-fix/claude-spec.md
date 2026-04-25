# Combined Specification — Signal Audit & Fix (Split 01)

## Objective

Audit and correct the signal pipeline in `src/essvi_bfly/` so that the core logic deciding when and in which direction to enter a butterfly trade is demonstrably correct and unit-tested. No backtest engine changes. No data pipeline changes.

---

## Package Context

**Root:** `src/essvi_bfly/`  
**Primary modules affected:**
- `signal/zscores.py` — rolling z-score and persistence counter
- `signal/candidate_selection.py` — direction assignment and edge calculation

**Reference (read-only):**
- `backtest/engine.py` — `_build_actions` defines LONG/SHORT_BFLY leg structure
- `config.py` — `BacktestConfig` carries all thresholds and windows

**New file:**
- `tests/test_signal.py` (top-level `tests/` directory at project root)

---

## Signal Pipeline Recap

### Step 1 — Residual IV
For each (bar_close, contract):
```
residual_iv = iv_market − iv_essvi
```
`iv_market` is inferred from market mid price; `iv_essvi` is the eSSVI surface value.

### Step 2 — Rolling Z-Score
Per contract, per session:
```
zscore = (residual_iv − rolling_mean(residual_iv, window)) / rolling_std(...)
```
Window = `zscore_window` bars (75 bars at 5-min = one full trading session of 9:15–15:30 IST).

### Step 3 — Persistence Counter
Count consecutive bars where `sign(zscore)` is unchanged. A positive count means the signal has held its direction for that many bars.

### Step 4 — Candidate Selection
For a set of three equidistant strikes (wing_low, body, wing_high):
- Skip if `same_sign_persistence < persistence_bars` (default 2)
- Skip if `|zscore| < entry_z` (default 1.5)
- Assign direction and compute edge
- Skip if edge ≤ 0 or edge/cost < `min_edge_to_cost_ratio`

---

## Verified Correct (No Code Change)

### Direction Assignment

The code at `signal/candidate_selection.py` lines 73–78:
```python
if body["zscore"] < 0:
    direction = "SHORT_BFLY"
    edge = market_premium - model_premium
else:
    direction = "LONG_BFLY"
    edge = model_premium - market_premium
```

**Verdict: correct.** Derivation:
- `residual_iv = iv_market - iv_essvi`
- z > 0 ⟹ body IV above eSSVI ⟹ body option overpriced ⟹ LONG_BFLY (sell dear body, buy wings)
- z < 0 ⟹ body IV below eSSVI ⟹ body option underpriced ⟹ SHORT_BFLY (buy cheap body, sell wings)
- This matches `_build_actions` in `engine.py`:
  - `LONG_BFLY` entry = BUY wing_low + SELL body×2 + BUY wing_high (standard long butterfly)
  - `SHORT_BFLY` entry = SELL wing_low + BUY body×2 + SELL wing_high (standard short butterfly)

Action: add a 3-line verification comment at the top of `candidate_selection.py`. No code change.

### Edge Formula

For LONG_BFLY: `edge = model_premium − market_premium`
- We pay `market_premium` (debit spread). Body is overpriced → model prices body lower → model_premium > market_premium. Edge > 0. ✓

For SHORT_BFLY: `edge = market_premium − model_premium`
- We receive `market_premium` (credit spread). Body is underpriced → body market_price < model_price → market_premium > model_premium. Edge > 0. ✓

Both premiums use `butterfly_value = low − 2×body + high`.

Action: add a clarifying comment. No code change.

---

## Bug 1 — Z-Score Rolling Window Crosses Session Boundaries

### Location
`signal/zscores.py`, function `add_residual_zscores`, lines 9–16.

### Current Code
```python
grouped = out.groupby("contract_name", group_keys=False)["residual_iv"]
min_periods = min(20, window)
out["residual_mean_roll"] = grouped.transform(
    lambda s: s.rolling(window, min_periods=min_periods).mean()
)
out["residual_std_roll"] = grouped.transform(
    lambda s: s.rolling(window, min_periods=min_periods).std()
)
```

Groups by `contract_name` only. The rolling window accumulates across trading sessions.
At 5-min bars, `zscore_window_5m = 75` bars = 375 minutes = 6.25 hours. One trading session
(9:15–15:30 IST) is also 375 minutes = 75 bars. The first z-score computation of a new session
uses the entire previous session as history — not just the current session.

### Fix
Group by `(contract_name, session_date)`:
```python
grouped = out.groupby(["contract_name", "session_date"], group_keys=False)["residual_iv"]
min_periods = min(20, window)
out["residual_mean_roll"] = grouped.transform(
    lambda s: s.rolling(window, min_periods=min_periods).mean()
)
out["residual_std_roll"] = grouped.transform(
    lambda s: s.rolling(window, min_periods=min_periods).std()
)
```

`session_date` already exists on the chain DataFrame (populated by `build_session_chain()`).
No new columns needed.

### min_periods
Keep `min_periods = min(20, window)`. At 5-min bars, this means:
- Bars 1–19 of each session: z-score is NaN → filtered by `same_sign_persistence < persistence_bars`
- Bars 20–74: partial-window estimate (20–74 observations)
- Bar 75+: full-window estimate

This is the intended warmup behavior and has been confirmed by the user.

---

## Bug 2 — Persistence Counter Crosses Session Boundaries

### Location
`signal/zscores.py`, last line of `add_residual_zscores` (approximately line 34).

### Current Code
```python
out["same_sign_persistence"] = out.groupby("contract_name", group_keys=False)["zscore"].apply(persistence)
```

Groups by `contract_name` only. The persistence counter carries the run count from the final bars
of the previous session into the first bars of the new session.

### Fix
Add `session_date` as a groupby key:
```python
out["same_sign_persistence"] = (
    out.groupby(["contract_name", "session_date"], group_keys=False)["zscore"]
    .apply(persistence)
)
```

### Persistence Counter Logic Verification

Hand trace on `[+1.2, +1.5, −1.3, −1.8, −2.0, NaN]`:
- sign(+1.2) = +1 → current=1, prev=+1
- sign(+1.5) = +1 → current=2, prev=+1  (same sign, increment)
- sign(−1.3) = −1 → current=1, prev=−1  (sign flip, reset to 1)
- sign(−1.8) = −1 → current=2, prev=−1
- sign(−2.0) = −1 → current=3, prev=−1
- sign(NaN→0) =  0 → current=0, prev= 0

Result: `[1, 2, 1, 2, 3, 0]`

Counter behavior:
- Starts at 1 on the first bar of each run ✓
- Increments by 1 for each additional same-sign bar ✓
- Resets to 0 (not 1) when sign is 0 (NaN treated as neutral) ✓
- The NEW run after sign flip starts at 1 (not 0) ✓

Implication: `same_sign_persistence >= 2` means at least 2 consecutive same-sign bars have occurred.

---

## Unit Tests — `tests/test_signal.py`

### Test Framework Setup
Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

### Required Test Cases

**1. `test_direction_long_bfly`**
- Input: body zscore = +2.0 (above entry_z=1.5), persistence = 3 (≥ persistence_bars=2)
- Expected: direction == "LONG_BFLY"
- Tests: `select_candidates()` returns a candidate with LONG_BFLY when z > 0

**2. `test_direction_short_bfly`**
- Input: body zscore = −2.0, persistence = 3
- Expected: direction == "SHORT_BFLY"

**3. `test_edge_long_bfly_positive`**
- Input: LONG_BFLY scenario where model_premium = 40, market_premium = 20
- Expected: edge = 20 (positive — structure is cheap relative to model)

**4. `test_edge_short_bfly_positive`**
- Input: SHORT_BFLY scenario where market_premium = 60, model_premium = 40
- Expected: edge = 20 (positive — structure is expensive relative to model)

**5. `test_persistence_counter`**
- Input z-score series: `[1.2, 1.5, -1.3, -1.8, -2.0, NaN]`
- Expected persistence:  `[1,   2,   1,    2,    3,    0  ]`
- Tests the `persistence()` function directly

**6. `test_zscore_rolling_within_session`**
- Input: synthetic 2-session panel for one contract, 30 bars each, with min_periods=5
- Expected: first 4 bars of EACH session have NaN z-score; bar 5+ of each session has a finite value
- Verifies that after the session-boundary fix, session 2's z-score is NaN at bar 1 (not contaminated by session 1)

### Minimal Test Helpers
Tests should use synthetic DataFrames built inline (no I/O, no parquet loading).
For direction/edge tests, construct a minimal 3-row DataFrame (wing_low, body, wing_high)
with the required columns (`zscore`, `same_sign_persistence`, `quote_ok`, `iv_essvi`,
`iv_market`, `mid`, `forward`, `strike`, `tau_years`, `expiry_code`, `option_side`, etc.)
and call `select_candidates()` directly.

For the persistence test, call `persistence()` directly on a pd.Series.

For the rolling test, call `add_residual_zscores()` on a constructed DataFrame with
`contract_name`, `session_date`, `bar_close`, and `residual_iv` columns.

---

## Non-Goals (Out of Scope)

- `backtest/engine.py` execution logic
- End-to-end pipeline or data loading
- `signal/straddle_selection.py` (parallel structure — deferred to a separate split)
- Performance profiling or parameter tuning

---

## Deliverables

1. `signal/zscores.py` — session-boundary fix for both rolling window and persistence counter
2. `signal/candidate_selection.py` — clarifying comments on direction and edge (no code change)
3. `tests/test_signal.py` — all 6 test cases passing
4. `pyproject.toml` — pytest added to dev extras
