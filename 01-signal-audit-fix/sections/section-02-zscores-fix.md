# Section 02 — zscores.py Session-Boundary Fix

## Overview

This section fixes the session-boundary bug in `src/essvi_bfly/signal/zscores.py`, function `add_residual_zscores`. It is independent of sections 01 and 03 and must be complete before section-04 (the test suite) can be run.

**File to modify:** `src/essvi_bfly/signal/zscores.py`

**Function to modify:** `add_residual_zscores`

No other files in this section.

---

## Acceptance Tests

The following tests (implemented in section-04) serve as the acceptance criteria for this fix:

- `test_zscore_rolling_within_session` — the regression guard. This test builds a two-session synthetic panel and asserts that session 2 bars 0-8 produce NaN z-scores (the rolling warmup re-starts at each session boundary). This test **must fail** against the current code and **must pass** after the fix.
- `test_persistence_counter` (Cases A and B) — pure unit tests on the `persistence()` helper. These are unaffected by the groupby change but live in the same module. They should pass both before and after the fix.

---

## Bug Diagnosis

### Rolling z-score leaks across session boundaries

The rolling window is `config.zscore_window` bars. In the default 5-minute bar configuration, `zscore_window_5m = 75`, which covers 375 minutes — exactly one full IST trading session (9:15 to 15:30). The current code groups only by `contract_name` when computing the rolling mean and standard deviation:

```python
grouped = out.groupby("contract_name", group_keys=False)["residual_iv"]
out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
out["residual_std_roll"]  = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
```

Because bars from different sessions are concatenated in the same series, the rolling window at bar 0 of day T reaches back into day T-1's data. The z-score at 9:15 on day T therefore reflects day T-1's volatility regime, not day T's.

### Persistence counter leaks across session boundaries

The same leakage applies to the persistence counter:

```python
out["same_sign_persistence"] = out.groupby("contract_name", group_keys=False)["zscore"].apply(persistence)
```

If the final bars of day T-1 had a positive z-score, those counts carry over to bar 0 of day T, making the counter appear to have already satisfied the minimum-bars requirement before the new session's signal has stabilized.

### `session_date` column is already present

The `session_date` column is guaranteed to exist on the chain DataFrame before `add_residual_zscores` is called. It is populated by `build_session_chain()` upstream. No upstream changes are required.

### `BacktestConfig.zscore_window` is a property

`config.zscore_window` is a `@property` on `BacktestConfig` that returns `zscore_window_5m` or `zscore_window_1m` based on `bar_freq`. The implementation reads this property, not the underlying field directly. No changes are made to `BacktestConfig` in this section.

---

## Three Sub-Changes Required

### 2a — Sort order

**Current:**
```python
out = chain.sort_values(["contract_name", "bar_close"]).copy()
```

**Fixed:**
```python
out = chain.sort_values(["contract_name", "session_date", "bar_close"]).copy()
```

This makes the ordering intent explicit: within a contract, bars are ordered by session date first, then by time within the session. This is robust against any data where bars from different sessions might appear interleaved in the input.

### 2b — Rolling window groupby

**Current:**
```python
grouped = out.groupby("contract_name", group_keys=False)["residual_iv"]
out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
out["residual_std_roll"]  = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
```

**Fixed:** Extract a local variable for the groupby key and replace the single-key groupby with a two-key groupby:

```python
group_keys = ["contract_name", "session_date"]
grouped = out.groupby(group_keys, group_keys=False)["residual_iv"]
out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
out["residual_std_roll"]  = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
```

The rolling window logic (window size, `min_periods`, the z-score arithmetic on the following line) is unchanged.

### 2c — Persistence counter groupby + `.reindex` guard

**Current:**
```python
out["same_sign_persistence"] = out.groupby("contract_name", group_keys=False)["zscore"].apply(persistence)
```

**Fixed:**
```python
out["same_sign_persistence"] = (
    out.groupby(group_keys, group_keys=False)["zscore"]
    .apply(persistence)
    .reindex(out.index)
)
```

**Why `.reindex(out.index)` is required:** When `.apply()` is used with a two-key groupby, pandas can produce a `(contract_name, session_date, original_index)` MultiIndex on the returned Series rather than the flat original index. This depends on the pandas version. Without `.reindex(out.index)`, the assignment to `out["same_sign_persistence"]` silently produces all-NaN values because the MultiIndex does not align with `out`'s RangeIndex. The `.reindex(out.index)` call drops any extra index levels and aligns back to the flat index, making the fix robust across pandas versions.

The `group_keys` variable is the same one defined in sub-change 2b — use it here as well.

---

## Complete Before/After

**Before (current broken code):**

```python
def add_residual_zscores(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = chain.sort_values(["contract_name", "bar_close"]).copy()
    window = config.zscore_window
    grouped = out.groupby("contract_name", group_keys=False)["residual_iv"]
    min_periods = min(20, window)
    out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
    out["residual_std_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
    out["zscore"] = (out["residual_iv"] - out["residual_mean_roll"]) / out["residual_std_roll"]

    def persistence(series: pd.Series) -> pd.Series:
        ...  # unchanged

    out["same_sign_persistence"] = out.groupby("contract_name", group_keys=False)["zscore"].apply(persistence)
    return out
```

**After (fixed code):**

```python
def add_residual_zscores(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = chain.sort_values(["contract_name", "session_date", "bar_close"]).copy()
    window = config.zscore_window
    group_keys = ["contract_name", "session_date"]
    grouped = out.groupby(group_keys, group_keys=False)["residual_iv"]
    min_periods = min(20, window)
    out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
    out["residual_std_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
    out["zscore"] = (out["residual_iv"] - out["residual_mean_roll"]) / out["residual_std_roll"]

    # persistence() is called here — it must be at module scope (see section-04 note)
    out["same_sign_persistence"] = (
        out.groupby(group_keys, group_keys=False)["zscore"]
        .apply(persistence)
        .reindex(out.index)
    )
    return out
```

---

## Invariants to Preserve

- The `persistence()` helper function body is **not modified** in this section. Its internal logic handles leading NaN values correctly: `np.sign(NaN.fillna(0)) == 0` sets `current = 0`, so NaN z-score bars during the session warmup window produce a persistence count of 0.
- The `add_residual_zscores` function signature is unchanged: `(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame`.
- `BacktestConfig` is not modified in this section.
- The `zscore` arithmetic line (`out["zscore"] = ...`) is unchanged.
- `min_periods = min(20, window)` is unchanged.

---

## Note: Moving `persistence` to Module Scope

Section-04 requires importing `persistence` directly for the `test_persistence_counter` tests. If `persistence` is currently defined as a nested function inside `add_residual_zscores`, it should be moved to module scope as part of implementing section-02 or section-04. The function body is unchanged — only its location in the file changes. The call inside `add_residual_zscores` will still resolve correctly once the function is at module scope.

**Implemented:** `persistence()` was moved to module scope in this section (body unchanged). Final file at `src/essvi_bfly/signal/zscores.py`: 41 lines, two top-level functions (`persistence`, `add_residual_zscores`).

---

## Dependencies

- **Depends on:** none (can be implemented immediately, in parallel with sections 01 and 03)
- **Blocks:** section-04 (test suite) — the `test_zscore_rolling_within_session` regression guard test will fail until this fix is applied
