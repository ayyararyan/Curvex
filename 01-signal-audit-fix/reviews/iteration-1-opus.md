# Opus Review

**Model:** claude-opus-4
**Generated:** 2026-04-25T00:00:00Z

---

# Review: Signal Audit & Fix Implementation Plan

## Summary

The plan is well-scoped, the diagnosis of the two session-boundary bugs is correct, and the fixes are minimal and surgical. The audit conclusions on direction and edge formulas are verified against `candidate_selection.py` (lines 73-78 and 66-72). However, several specifications in the test plan are mathematically inconsistent or under-specified, and there are a few real footguns worth addressing before implementation.

---

## Correctness / Footguns

### 1. `min_periods` arithmetic in `test_zscore_rolling_within_session` is wrong (Section: Test Specifications, lines 134-142)

The plan states: "Set `min_periods = 5` by injecting a config with `zscore_window = 10` (so `min_periods = min(20, 10) = 10` — adjust config or use a lower window to get a testable min_periods of 5 within a 30-bar session)."

This is internally contradictory. Looking at `zscores.py` line 13: `min_periods = min(20, window)`. With `window=10`, `min_periods = 10`, not 5. The plan then asserts "Session 1, bars 0–3: z-score is NaN; Session 1, bar 4+: z-score is non-NaN" — that requires `min_periods = 5`, but the code will produce NaN for bars 0–8 and non-NaN at bar 9+.

**Fix:** Either (a) change the assertions to match `min_periods=10` behavior (NaN for bars 0–8, non-NaN at bar 9+, with `window=10`, 30 bars per session), or (b) change `min_periods` derivation in `zscores.py` (out of scope per Key Invariants line 167), or (c) parameterize `min_periods` (config change — also out of scope). Pick (a).

### 2. Critical bug in `persistence()` interaction with the new groupby — needs explicit test coverage

After the fix, `out.groupby(["contract_name", "session_date"], group_keys=False)["zscore"].apply(persistence)` will be called once per `(contract, session_date)` group. Within `persistence()`, the function uses `series.fillna(0)`, then `np.sign(0) == 0`, which resets `current` to 0. But more importantly: the loop initializes `prev = 0`. The very first non-NaN value in a session will hit the `elif sign == prev` branch where `prev=0` and `sign != 0`, so it goes to `else: current = 1`. That's correct.

But look at the rolling z-score at session start: for `min_periods=20` bars are NaN. The `persistence()` over a session that has, say, NaN for bars 0–19 and real values 20–74, will return zeros for bars 0–19 (because `np.sign(NaN.fillna(0)) == 0`), then count from bar 20. This is correct behavior.

**Recommend** adding a 7th test (or extending `test_persistence_counter`): hand-trace a session-aware case `[NaN, NaN, 1.5, 1.8, NaN, 2.0]` → `[0, 0, 1, 2, 0, 1]` to lock this in.

### 3. `apply(persistence)` index alignment risk

The current `out["same_sign_persistence"] = out.groupby(...)["zscore"].apply(persistence)` (line 34 of zscores.py) relies on `apply` returning a Series with the right MultiIndex that pandas then aligns back to `out`. With `group_keys=False` the alignment uses the inner index. With **two** groupby keys, pandas' `apply` on a SeriesGroupBy will sometimes return a Series with a `(contract_name, session_date, original_index)` MultiIndex, which will not align cleanly into `out` and can produce all-NaN.

**Action:** The plan should explicitly verify (in a test or a code review checklist) that after the change to `groupby(["contract_name", "session_date"], group_keys=False)`, `same_sign_persistence` ends up as integer values aligned to `out`'s index, not NaN. The safest pattern is:

```python
out["same_sign_persistence"] = (
    out.groupby(["contract_name", "session_date"], group_keys=False)["zscore"]
       .apply(persistence)
       .reindex(out.index)
)
```

Or use `.transform(...)` if the function can be written transform-compatibly (it can't easily because of the running state). This is the single highest-risk area of the change and the plan does not mention it.

### 4. Sort order must include `session_date`

`zscores.py` line 10 sorts by `["contract_name", "bar_close"]`. After grouping by `(contract_name, session_date)`, the rolling computation needs the rows of each group in chronological order. Since `session_date` is monotone in `bar_close` for a given contract, this happens to remain correct, but the plan should add `session_date` to the sort to make the invariant explicit and robust against future data where bars could conceivably appear out of order. Recommend `sort_values(["contract_name", "session_date", "bar_close"])`.

### 5. `np.sign(0)` and zero z-scores

The plan (line 130) says "Resets to 0 for NaN values (which `np.sign(0)` maps to 0)." This is technically true but misleading: a real, non-NaN z-score of exactly 0.0 will also reset the persistence counter to 0. This is almost never going to happen in practice (z is float arithmetic), but it's worth noting in the comment block at the top of `persistence()`.

---

## Test Specification Issues

### 6. `test_edge_long_bfly_positive` — model_premium computation is not bypassable (lines 104-108)

The plan instructs: "construct a scenario where the body IV priced at `iv_essvi` gives a model butterfly premium of 40 and the market butterfly premium is 20." But `select_candidates` calls `price_option_forward` on each leg using `forward, strike, tau_years, risk_free_rate, iv_essvi, option_side`. The test must either:
- Construct synthetic BS-consistent inputs that produce premiums 40 and 20 (non-trivial), or
- Mock `price_option_forward`, or
- Drop the exact equality assertion and just assert `theoretical_edge > 0` and that direction sign matches.

**Recommend:** rewrite as "theoretical_edge > 0 and direction == LONG_BFLY" with synthetic IVs chosen so `iv_market > iv_essvi` for the body. The economic test is: positive z (body market_iv high relative to essvi) → LONG_BFLY → positive edge.

### 7. `mid` vs the price column the engine actually uses

`_structure_value` (line 30) uses the column `"mid"`. The synthetic test data needs to set `mid` directly. The plan doesn't mention this column explicitly. Add a list of required columns to the test spec: `mid, strike, contract_name, quote_ok, iv_essvi, iv_market, forward, tau_years, spread, lot_size, contract_multiplier, zscore, same_sign_persistence, residual_iv, bar_close, root_symbol, expiry_code, option_side, session_date`.

### 8. Diagnostics DataFrame is required input but not mentioned

`select_candidates` takes `diagnostics: pd.DataFrame` (line 35) and filters via `diag_ok` (line 38) on columns `converged, rmse, bar_close, root_symbol, expiry_code`. The four direction/edge tests must construct a synthetic `diagnostics` DataFrame too.

### 9. `enforce_otm_structure_side` defaults to True — test inputs must satisfy it

Lines 60-65 of `candidate_selection.py`: with default `enforce_otm_structure_side=True`, CE bodies must have `strike >= forward` and PE bodies `strike <= forward`. Tests must set `option_side` and forward consistently, or pass a config with `enforce_otm_structure_side=False`.

### 10. Persistence counter input: 1.2 is not a z-score

`test_persistence_counter` uses input `[1.2, 1.5, ...]`. The function takes the raw series and does sign internally, so any non-NaN values work. Note: 0.0 in the input would also map to a sign of 0 and reset the counter — worth noting, but the test inputs are fine.

---

## Architectural / Process

### 11. `__init__.py` location

Plan line 156 places `tests/__init__.py` for "test discovery." Modern pytest does **not** require `__init__.py`. Adding it changes test collection semantics. Recommend omitting it. Instead, add `pythonpath = ["src"]` to `[tool.pytest.ini_options]` so tests can import `from essvi_bfly...` without an editable install.

### 12. Behavior change is real and downstream-visible

The plan states the change is "transparent to callers" (line 165). That's true at the API level, but the **values** of `zscore` and `same_sign_persistence` will change for every bar within the first ~20 bars of every session. Any cached intermediates must be regenerated.

### 13. The audit conclusion "no change" for direction is correct but undertested

A smoke test that imports `_build_actions` and asserts the action list for a LONG_BFLY entry has `(BUY, wing_low), (SELL, body)×2, (BUY, wing_high)` would be a one-line guard against future drift.

### 14. Missing test: exit/holding logic untouched but unverified

Out of scope per the split, but worth flagging: the same session-boundary bug likely affects exit conditions (`exit_z`, `stop_z`) which presumably read the same `zscore` column. The fix propagates to exits transparently. Plan should explicitly call out "no audit performed of exit logic" so the next split picks it up.

---

## Minor

- Line 50: "first 19 bars of each session produce NaN z-scores" — with `min_periods=20`, the first **20** bars produce NaN (bars 0–19). Off-by-one in the prose.
- Line 175: `zscore_window_5m` / `zscore_window_1m` are separate fields; `BacktestConfig.zscore_window` is a `@property` that picks one based on `bar_freq`. Tests that override window must set both the window field and `bar_freq`.
- The plan's test count says "six tests" — matches the six described. Good.

---

## Top 3 Action Items Before Coding

1. Resolve the `min_periods` arithmetic in `test_zscore_rolling_within_session` (item 1) — the test as specified will fail.
2. Add explicit handling/verification for `apply()` index alignment after the two-key groupby (item 3) — highest risk of silent bug.
3. Specify the full required column list and synthetic `diagnostics` DataFrame for the candidate-selection tests (items 7, 8, 9) — without these the tests cannot be written.
