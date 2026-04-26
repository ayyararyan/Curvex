<!-- PROJECT_CONFIG
runtime: python-uv
test_command: uv run pytest tests/ -v
END_PROJECT_CONFIG -->

<!-- SECTION_MANIFEST
section-01-structural-prereqs
section-02-engine-audit
section-03-time-stop-exit
section-04-nav-and-resilience
section-05-performance-index
section-06-smoke-test
section-07-full-run
END_MANIFEST -->

# Implementation Sections Index

## Dependency Graph

| Section | Depends On | Blocks | Parallelizable |
|---|---|---|---|
| section-01-structural-prereqs | — | 02, 03, 04, 05 | No |
| section-02-engine-audit | 01 | 03, 04 | No |
| section-03-time-stop-exit | 02 | 04, 07 | No |
| section-04-nav-and-resilience | 03 | 07 | No |
| section-05-performance-index | 01 | 07 | Yes (parallel with 02–04) |
| section-06-smoke-test | 01 | 07 | Yes (parallel with 02–05) |
| section-07-full-run | 02, 03, 04, 05, 06 | — | No |

## Execution Order

1. **section-01** — structural prerequisites (no dependencies)
2. **section-02** — engine audit and cashflow fix (after 01)
3. **section-03, section-05, section-06** — time-stop exit, performance index, and smoke-test can proceed concurrently after 02 completes (sections 05 and 06 only depend on 01, so they could even run in parallel with 02 if edits are isolated to separate files)
4. **section-04** — nav output and session resilience (after 03)
5. **section-07** — full run (after all other sections complete)

## Section Summaries

### section-01-structural-prereqs
Add `exit_type: str | None` and `exit_fill_quality: str | None` fields to `ButterflyTrade` in `portfolio/structures.py`. Add module-level `logging` to `engine.py` and configure a stderr handler in `__main__.py`. These changes are prerequisites for all engine modifications. No tests required beyond confirming imports are clean.

### section-02-engine-audit
Read `engine.py._build_actions` and verify (or fix) the 4-leg action sequences for all (direction × is_exit) combinations. Fix the `orders=1` → `orders=4` bug in both `estimate_transaction_cost` call sites in `_simulate`. Write unit tests (`tests/test_engine.py`) for `_build_actions` exhaustively (4 tests) and a hand-computed numerical test for `_cashflow_from_fills` confirming sign convention and scale.

### section-03-time-stop-exit
Add `_fill_leg_with_fallback` method to `BacktestEngine` (uses `sp1`/`bp1` first, falls back to `lp` with synthetic spread adjustment and staleness guard). Rewrite `_simulate_exit` as a two-phase loop: primary exit (trigger-based fill), then time-stop fallback at `max_holding_bars`. Handle missing-wing-row case by walking back up to 3 bars. Update the return tuple to 7 elements (adds `exit_type` and `fill_quality`). Update all call sites in `_simulate` to unpack the new tuple. Write unit tests covering all exit types, priority rules, fallback paths, and the missing-row walkback.

### section-04-nav-and-resilience
Add `_build_nav` to compute `cumulative_pnl` column in the nav output. Fix session error handling in `run()`: add narrow `try/except` for data-loading errors only (FileNotFoundError, ArrowInvalidError, ArrowIOError, OSError, EmptyDataError, ParserError) with `logger.warning`. Add end-of-run check raising `RuntimeError` if zero rows were produced for any single root symbol. Write unit tests for the skip behavior (mock `build_session_chain` to raise), `_build_nav` correctness, and the RuntimeError guard.

### section-05-performance-index
Add `_build_contract_bar_index` to `BacktestEngine` that pre-computes a `dict[contract_name → sorted np.ndarray of bar_close]` before the candidate loop in `_simulate`. Update `_next_bar_for_contract` to use `np.searchsorted` on this index instead of filtering the full chain DataFrame. Write unit tests for the index construction and `_next_bar_for_contract` correctness (including the None case and the O(log N) binary search path).

### section-06-smoke-test
Create `scripts/smoke_test_pipeline.py` with a `check(label, condition, detail)` helper and an 11-check `main()` function (chain non-empty, tau > 0, ATM mid > 0, forward within 1% of spot, quote_ok ≥ 50%, calibration convergence ≥ 3 slices, bar count ≥ 60, strike coverage ≥ 5, no duplicate index keys, underlying resolved, session-boundary z-score NaN guard). Accepts `--session`, `--symbol`, and `--rmse-limit-override` CLI flags. Exits 0 on all pass, 1 on any failure. Write minimal pytest tests for the `check()` helper and the exit-code behavior.

### section-07-full-run
Run the full backtest with the spec config (`uv run python scripts/run_backtest.py --strategy butterfly --bar-freq 5min --root-symbol NIFTY --root-symbol BANKNIFTY`). Document and fix any runtime errors encountered. Verify all 6 CSVs are produced. Manually spot-check 5 trades from `butterfly_trades.csv` against the 6 criteria in `claude-plan.md` Section 9. Record the calibration summary stats (per-symbol convergence rate, RMSE distribution). No automated tests — this is an integration and verification step.
