# Implementation Plan — Signal Audit & Fix (Split 01)

## What We're Building

This plan covers targeted corrections to the butterfly signal pipeline in the `essvi_bfly` Python package. The pipeline determines when and in which direction to enter an eSSVI butterfly option spread. Before any backtest runs, the core signal logic must be provably correct. This split audits that logic, fixes two session-boundary bugs, and introduces a pytest test suite. It does not touch the backtest engine, data loading, or straddle signal path.

---

## Background: The Signal Pipeline

The package operates on NIFTY/BANKNIFTY option data sampled at 5-minute bars. For each bar, it:

1. Infers `iv_market` for each option from the market mid-price via Black-Scholes inversion.
2. Fits an eSSVI surface to market IVs and evaluates `iv_essvi` per contract.
3. Computes `residual_iv = iv_market − iv_essvi` for each contract.
4. Rolls a z-score over `residual_iv` within each contract's history.
5. Counts how many consecutive bars the z-score has held the same sign (persistence counter).
6. Selects butterfly structures (wing_low / body / wing_high at equidistant strikes) where the body's z-score has exceeded a threshold for at least `persistence_bars` consecutive bars.
7. Assigns a direction (LONG_BFLY or SHORT_BFLY) and computes an edge in rupees per lot.

The economic logic: if the body strike's IV is persistently above the eSSVI surface, the body option is overpriced relative to the model. The correct trade is a **long butterfly** — sell the overpriced body, buy the wings. If body IV is persistently below the surface, it is underpriced and the correct trade is a **short butterfly** — buy the cheap body, sell the wings.

---

## What Was Found in the Audit

### Direction Assignment — Correct, No Change

In `signal/candidate_selection.py`, the assignment:

```python
if body["zscore"] < 0:   direction = "SHORT_BFLY"
else:                     direction = "LONG_BFLY"
```

is correct. A negative z-score means the body residual is below its rolling mean — body IV is underpriced — and SHORT_BFLY (buy cheap body, sell wings) is the right response. A positive z-score means body IV is overpriced and LONG_BFLY (sell dear body, buy wings) is correct.

This mapping is consistent with `engine.py`'s `_build_actions`, where LONG_BFLY entry executes BUY wing_low + SELL body × 2 + BUY wing_high (the standard industry definition of a long butterfly — verified against CME Group and Hull's *Options, Futures, and Other Derivatives*).

### Edge Formula — Correct, No Change

For LONG_BFLY, `edge = model_premium − market_premium`. Both premiums use the butterfly formula `low − 2 × body + high`. When the body is overpriced, the model (which prices the body at fair value) produces a higher butterfly premium than the market (which subtracts the inflated body price more aggressively). Edge is positive when the market butterfly is cheaper than fair value — i.e., we are buying a structure that the model considers valuable.

For SHORT_BFLY, `edge = market_premium − model_premium`. When the body is underpriced, the market butterfly premium is higher than the model's (because the cheaper body is subtracted less aggressively). Edge is positive when the market butterfly is more expensive than fair value — i.e., we are selling a structure at above fair value.

### Session-Boundary Bug in Rolling Z-Score — Must Fix

In `signal/zscores.py`, `add_residual_zscores` groups residual IV series by `contract_name` only when computing the rolling mean and standard deviation. Because the rolling window is 75 bars at 5-min frequency (= one full IST trading session of 375 minutes), every z-score at the start of a new session is computed entirely from the previous session's data. This is wrong: the z-score at 9:15 on day T reflects day T-1's volatility regime, not day T's.

The fix is to group by `(contract_name, session_date)` instead. The `session_date` column already exists on the chain DataFrame. After the fix, the rolling window resets at each session open. With `min_periods = min(20, window) = 20`, the first 20 bars of each session (bars 0–19) produce NaN z-scores (those bars are naturally excluded from candidate selection because `same_sign_persistence` stays at 0, below the 2-bar threshold).

### Session-Boundary Bug in Persistence Counter — Must Fix

The same `add_residual_zscores` function also groups the persistence counter by `contract_name` only. If the last several bars of day T-1 had a positive z-score, those bars feed into the session-open bar of day T, making the counter appear to have already satisfied the persistence requirement before the new day's signal has stabilized. The fix is the same: add `session_date` to the groupby key for the persistence counter.

**Index alignment risk:** When `.apply(persistence)` is used with a two-key groupby, pandas can produce a `(contract_name, session_date, original_index)` MultiIndex on the result, which will not align back into `out` and will produce all-NaN values silently. The implementation must add `.reindex(out.index)` after the `.apply(persistence)` call to guarantee correct alignment regardless of pandas version behavior.

---

## Changes Required

### Change 1 — Comments in `signal/candidate_selection.py`

At the top of the `select_candidates` function, add a comment block documenting that the direction assignment has been verified correct: z < 0 → SHORT_BFLY (buy underpriced body), z ≥ 0 → LONG_BFLY (sell overpriced body), and this is consistent with `_build_actions` in `engine.py`. The comment should also note that z = 0 never reaches this branch in practice because `abs(z) < entry_z` filters it out before direction is assigned.

No code changes to this file are needed.

### Change 2 — Session-Boundary Fix in `signal/zscores.py`

Three sub-changes in `add_residual_zscores`:

**2a. Sort order.** Change `sort_values(["contract_name", "bar_close"])` to `sort_values(["contract_name", "session_date", "bar_close"])`. This makes the ordering intent explicit and robust against any data where bars from different sessions might appear interleaved.

**2b. Rolling window groupby.** Replace the single-key `groupby("contract_name")` with a two-key `groupby(["contract_name", "session_date"])` for the `.transform(lambda s: s.rolling(...))` calls that produce `residual_mean_roll` and `residual_std_roll`. The rest of the rolling logic (window size, min_periods, the z-score arithmetic) is unchanged.

**2c. Persistence counter groupby.** Replace the single-key `groupby("contract_name")` with `groupby(["contract_name", "session_date"])` for the `.apply(persistence)` call that produces `same_sign_persistence`. Add `.reindex(out.index)` after the `.apply(persistence)` call to guard against MultiIndex alignment issues that can arise with two-key groupby in some pandas versions.

The two `.groupby` calls should use the same key tuple for consistency; consider extracting it as a local variable `group_keys = ["contract_name", "session_date"]`.

No changes to the `persistence()` helper function itself — its internal logic is correct. The function handles leading NaN values correctly: `np.sign(NaN.fillna(0)) == 0`, which sets `current = 0` and `prev = 0`, so the first non-NaN bar after warmup starts a fresh run with count = 1.

Note on `BacktestConfig.zscore_window`: this is a `@property` on `BacktestConfig` that selects between `zscore_window_5m` and `zscore_window_1m` based on `bar_freq`. The implementation reads `config.zscore_window` (the property). Tests that need to control the window must set both the underlying field (e.g., `zscore_window_5m`) and the `bar_freq` field, not just one.

### Change 3 — Pytest Setup in `pyproject.toml`

Add `pytest>=8.0` to dev dependencies. Add a `[tool.pytest.ini_options]` section with:
- `testpaths = ["tests"]`
- `pythonpath = ["src"]` — this allows tests to `from essvi_bfly...` without requiring an editable install

Do not add `tests/__init__.py` — modern pytest discovers test files without it, and its presence changes import semantics.

### Change 4 — `tests/test_signal.py`

Create `tests/test_signal.py` at the project root level (alongside `src/`). The file imports from `essvi_bfly.signal.zscores`, `essvi_bfly.signal.candidate_selection`, and `essvi_bfly.backtest.engine`. All tests are pure unit tests — no I/O, no parquet loading.

---

## Synthetic Test Data Requirements

Tests that call `select_candidates` must provide two DataFrames:

**Chain DataFrame** (at minimum 3 rows: wing_low, body, wing_high):

| Column | Notes |
|---|---|
| `contract_name` | Any string |
| `session_date` | Any date value |
| `bar_close` | pd.Timestamp |
| `root_symbol` | e.g., "NIFTY" |
| `expiry_code` | e.g., "26JAN" |
| `option_side` | "CE" or "PE" |
| `strike` | float — must be equidistant for all three legs |
| `forward` | float — for CE: body_strike >= forward; for PE: body_strike <= forward (or set `enforce_otm_structure_side=False`) |
| `tau_years` | small positive float |
| `mid` | float — used by `_structure_value` for market_premium |
| `quote_ok` | True |
| `iv_market` | float |
| `iv_essvi` | float |
| `residual_iv` | `iv_market - iv_essvi` |
| `zscore` | float — set for body; wings value does not affect direction assignment |
| `same_sign_persistence` | int — set for body |
| `spread` | float — small |
| `lot_size` | 1 (to simplify rupee assertions) |
| `contract_multiplier` | 1 (to simplify rupee assertions) |

**Diagnostics DataFrame** (at minimum 1 row matching the bar/root/expiry of the synthetic chain):

| Column | Notes |
|---|---|
| `bar_close` | Must match chain's bar_close |
| `root_symbol` | Must match |
| `expiry_code` | Must match |
| `converged` | True |
| `rmse` | < `calibration_rmse_limit` (default 0.02) |

**Config recommendations for tests:**
- `enforce_otm_structure_side = False` (simplest; otherwise forward/strike must be set consistently)
- `require_positive_edge = True` (test-relevant — must ensure iv_market/iv_essvi values produce a positive edge)
- `zscore_window_5m = 10` with `bar_freq = "5min"` for the rolling test (small window finishes warmup within a 30-bar session)

---

## Test Specifications

### `test_direction_long_bfly`

Set `body["zscore"] = +2.0`, `body["same_sign_persistence"] = 3`, `iv_market > iv_essvi` for body (so market_premium < model_premium → edge > 0). Assert returned candidate has `direction == "LONG_BFLY"`.

### `test_direction_short_bfly`

Set `body["zscore"] = -2.0`, `body["same_sign_persistence"] = 3`, `iv_market < iv_essvi` for body (so market_premium > model_premium → edge > 0). Assert returned candidate has `direction == "SHORT_BFLY"`.

### `test_edge_long_bfly_positive`

With `iv_market > iv_essvi` for the body (overpriced body), assert that `candidate.theoretical_edge > 0` for the returned LONG_BFLY candidate. Do not assert exact rupee values — the key invariant is that the sign is positive (we identified a cheap structure relative to fair value).

### `test_edge_short_bfly_positive`

With `iv_market < iv_essvi` for the body (underpriced body), assert that `candidate.theoretical_edge > 0` for the returned SHORT_BFLY candidate.

### `test_persistence_counter`

Call `persistence()` directly on a `pd.Series`. Two cases:

**Case A — Sign flip:**
Input: `[1.2, 1.5, -1.3, -1.8, -2.0, float('nan')]`
Expected: `[1, 2, 1, 2, 3, 0]`

**Case B — Leading NaN (session warmup pattern):**
Input: `[float('nan'), float('nan'), 1.5, 1.8, float('nan'), 2.0]`
Expected: `[0, 0, 1, 2, 0, 1]`

Case B exercises the session-open behavior where z-scores are NaN during the min_periods warmup window, then become real values after warmup.

Assertions: use `list(result) == expected_list` for exact equality.

### `test_zscore_rolling_within_session`

Build a two-session DataFrame for a single `contract_name`:
- 30 bars per session at 5-min frequency (arbitrary, deterministic values for `residual_iv`)
- `session_date` set to two different dates (e.g., "2024-01-01" and "2024-01-02")
- `bar_close` timestamps consistent with session dates

Use a config with `zscore_window_5m = 10` and `bar_freq = "5min"`. This gives `min_periods = min(20, 10) = 10`.

Call `add_residual_zscores(chain, config)` and assert:
- Session 1, bars 0–8: `zscore` is NaN (10 bars needed before a finite value)
- Session 1, bar 9+: `zscore` is finite
- Session 2, bars 0–8: `zscore` is NaN ← **key regression guard; would fail before the fix**
- Session 2, bar 9+: `zscore` is finite

Also assert `same_sign_persistence.isna().sum() == 0` (all persistence values are integers, not NaN — verifying the `.reindex` fix worked).

### `test_build_actions_long_bfly_convention`

Import `BacktestEngine` and call `_build_actions` with a mock candidate whose `direction = "LONG_BFLY"` and `is_exit = False`. Assert the returned action list is:
```
[("BUY", wing_low, ...), ("SELL", body, ...), ("SELL", body, ...), ("BUY", wing_high, ...)]
```

This test guards the audit verdict (LONG_BFLY = buy wings, sell body = standard convention) against future engine drift. If `_build_actions` becomes a static or standalone function, import accordingly.

---

## File and Directory Structure After This Split

```
src/essvi_bfly/
  signal/
    candidate_selection.py    (comment added, no code change)
    zscores.py                (sort_values fix; groupby fix for rolling and persistence; .reindex guard)
  ...
tests/
  test_signal.py              (8 tests)
pyproject.toml                (pytest added to dev extras; pythonpath = ["src"])
```

No `tests/__init__.py`.

---

## Key Invariants to Preserve

- The `persistence()` function signature and return type must not change — it is called via `.apply()` on a grouped Series and must return a same-indexed Series.
- The `add_residual_zscores` function signature must not change — it takes a chain DataFrame and a `BacktestConfig` and returns a DataFrame. The groupby change is internal.
- The `select_candidates` function signature must not change.
- `BacktestConfig` must not be modified in this split (no new fields needed; `min_periods` is derived inline as `min(20, window)` and is acceptable as-is per the user's decision).

---

## Non-Goals (Out of Scope)

- `backtest/engine.py` execution logic — the `test_build_actions_long_bfly_convention` test is read-only against the engine, not a modification
- End-to-end pipeline or data loading
- `signal/straddle_selection.py` (parallel structure — deferred to a separate split)
- Performance profiling or parameter tuning
- Exit/stop logic audit — the session-boundary fix in z-scores propagates transparently to any downstream exit condition that reads the `zscore` column, but a dedicated audit of exit logic is deferred to split 02

---

## Assumptions

- `session_date` is always present and populated on the chain DataFrame before `add_residual_zscores` is called. This is guaranteed by the upstream `build_session_chain()` function.
- Contracts that span multiple sessions (e.g., weekly expiries tracked across days) have the same `contract_name` across sessions but different `session_date` values — the two-key groupby correctly handles this case by isolating each session's rolling computation.
- The `.reindex(out.index)` on the persistence counter is safe because `out` has a unique RangeIndex (it is a `.copy()` of the input chain sorted by contract+session+time). If the chain ever has duplicate index values, this assumption breaks — but that would be a data integrity issue upstream.
