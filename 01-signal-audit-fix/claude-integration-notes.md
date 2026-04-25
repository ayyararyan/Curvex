# Integration Notes — Opus Review Feedback

## Integrating

### Item 1 — min_periods arithmetic fix in test spec
**Integrating.** The test spec had an internal contradiction: window=10 gives min_periods=10, but the assertions said bars 0-3 are NaN (which implies min_periods=5). Correcting to: with window=10, min_periods=10, so bars 0-9 produce NaN and bar 9+ is non-NaN.

### Item 3 — apply(persistence) index alignment risk
**Integrating.** This is the highest-risk change. Adding `.reindex(out.index)` after the `.apply(persistence)` call to guarantee no MultiIndex misalignment under the two-key groupby. Also adding an assertion in the test that `same_sign_persistence.isna().sum() == 0` on a well-formed input.

### Item 4 — Add session_date to sort_values
**Integrating.** Makes the sort order intent explicit and robust. Change `sort_values(["contract_name", "bar_close"])` to `sort_values(["contract_name", "session_date", "bar_close"])`.

### Item 6 — Edge tests rewritten to assert edge > 0 (not exact rupee values)
**Integrating.** The exact rupee value approach required BS-consistent synthetic inputs, which is non-trivial. Replacing with: assert `theoretical_edge > 0` for LONG_BFLY when `iv_market > iv_essvi` for the body (and vice versa for SHORT_BFLY). This tests the correct economic invariant.

### Item 7/8/9 — Test column list, diagnostics DataFrame, enforce_otm_structure_side
**Integrating.** Adding explicit list of all required synthetic DataFrame columns. Adding note that tests must construct a minimal `diagnostics` DataFrame. Adding note to set `enforce_otm_structure_side=False` in config for simplicity, or ensure OTM constraint is satisfied in synthetic data.

### Item 11 — Remove tests/__init__.py, add pythonpath
**Integrating.** Remove `tests/__init__.py` from plan (not needed for modern pytest). Add `pythonpath = ["src"]` to `[tool.pytest.ini_options]` so tests can `from essvi_bfly...` without editable install.

### Item 2 (extended) — Leading-NaN persistence test
**Integrating.** Adding a 7th test case to `test_persistence_counter`: series `[NaN, NaN, 1.5, 1.8, NaN, 2.0]` → expected `[0, 0, 1, 2, 0, 1]`. This exercises the session-open pattern where z-scores start as NaN during warmup.

### BacktestConfig.zscore_window property clarification
**Integrating.** Noting that `zscore_window` is a `@property` selecting between `zscore_window_5m` and `zscore_window_1m` based on `bar_freq`. Tests must set the appropriate field (`zscore_window_5m`) and also set `bar_freq = "5min"`.

### Item 13 — Smoke test for _build_actions direction consistency
**Integrating.** Adding a 8th test case (`test_build_actions_long_bfly_convention`) that imports the engine and verifies LONG_BFLY entry produces BUY/SELL/SELL/BUY action pattern. This guards the audit verdict against future engine drift.

## Not Integrating

### Item 12 — Downstream artifacts note
**Not integrating.** True observation but this is operational knowledge for the developer running the backtest, not something the implementation plan needs to specify. The developer will regenerate outputs as needed.

### Item 14 — Exit logic audit note
**Not integrating as a task.** Already called out in the plan as out of scope. Adding a single sentence to the non-goals section noting that the session-boundary fix propagates to exit-path zscore reads, but exit logic audit is deferred to split 02.
