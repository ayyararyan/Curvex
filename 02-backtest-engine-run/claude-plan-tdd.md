# TDD Plan — Split 02: Backtest Engine & End-to-End Run

Tests mirror the structure of `claude-plan.md`. All tests go in `tests/test_engine.py` (new file) unless noted. Run with `uv run pytest tests/ -v`.

---

## Section 1: Verify `_build_actions`

### Tests to write first

```python
# Test: LONG_BFLY entry returns actions BUY/SELL/SELL/BUY for wing_low/body/body/wing_high
# Test: LONG_BFLY exit returns SELL/BUY/BUY/SELL (exact entry reversal)
# Test: SHORT_BFLY entry returns SELL/BUY/BUY/SELL
# Test: SHORT_BFLY exit returns BUY/SELL/SELL/BUY
# Test: body contract name appears twice in all four cases
# Test: contract names in output match candidate.wing_low_contract, candidate.body_contract, candidate.wing_high_contract
```

Use a synthetic `ButterflyCandidate` with fixed contract names ("LOW", "BODY", "HIGH") and minimal pandas Series as quote rows. No IO.

---

## Section 2: Fix `_cashflow_from_fills` and Transaction Costs

### Tests to write first

```python
# Test: LONG_BFLY entry cashflow with known prices: wing_low=50 BUY, body=80 SELL×2, wing_high=50 BUY
#   scale=1.0 → expected cashflow = -50 + 80 + 80 - 50 = +60.0 (assert exact)
# Test: LONG_BFLY exit cashflow (reverse actions): body BUY×2, wings SELL
#   wing_low=45 SELL, body=65 BUY×2, wing_high=45 SELL → expected = +45 - 65 - 65 + 45 = -40.0
# Test: pnl = entry_cashflow + exit_cashflow is positive for a profitable reversal
#   (use the two cases above: 60 + (-40) - cost > 0 if cost < 20)
# Test: scale correctly applied: repeat above with scale=50 (lot_size=50, multiplier=1)
#   cashflow = 60 × 50 = 3000.0
# Test: estimate_transaction_cost called with orders=4 (not orders=1)
#   mock estimate_transaction_cost; assert called with orders=4
```

All unit tests — no IO, no parquet loading.

---

## Section 3: Time-Stop Exit

### Tests to write first

```python
# Test: _fill_leg_with_fallback returns sp1 for BUY when sp1 > 0
# Test: _fill_leg_with_fallback returns bp1 for SELL when bp1 > 0
# Test: _fill_leg_with_fallback falls back to lp × (1 + half_spread) for BUY when sp1 is NaN
# Test: _fill_leg_with_fallback falls back to lp × (1 - half_spread) for SELL when bp1 is NaN
# Test: _fill_leg_with_fallback returns filled=False when both sp1 and lp are NaN
# Test: _simulate_exit returns an exit (not None) when no trigger fires within max_holding_bars
#   (time-stop path) — use synthetic chain with no z-score crossing thresholds
# Test: _simulate_exit exit_type='profit_take' when |z| <= exit_z
# Test: _simulate_exit exit_type='stop_loss' when |z| >= stop_z
# Test: _simulate_exit exit_type='stop_loss' wins when both triggers fire at same bar
# Test: _simulate_exit exit_type='time_stop' when max_holding_bars reached without trigger
# Test: _simulate_exit staleness guard sets exit_fill_quality='degraded' when lp is stale
# Test: _simulate_exit returns 7-tuple (not 5-tuple) — unpack check
```

Use synthetic DataFrames built from dictionaries with known zscores and quote rows. No parquet IO.

---

## Section 4: Nav Output — `cumulative_pnl`

### Tests to write first

```python
# Test: _build_nav produces cumulative_pnl column
# Test: cumulative_pnl is the cumulative sum of pnl, sorted by trade_id
#   3 trades with pnl=[10, -5, 20] → cumulative=[10, 5, 25]
# Test: _build_nav preserves trade_id column
# Test: butterfly_nav.csv written to disk contains cumulative_pnl column (integration)
```

---

## Section 5: Session-Level Error Handling

### Tests to write first

```python
# Test: run() skips a session when FileNotFoundError raised by build_session_chain
#   (mock build_session_chain to raise; assert session appears in warning log, not in output)
# Test: run() skips a session when OSError raised
# Test: run() does NOT catch KeyError from _simulate (logic error must propagate)
# Test: run() raises RuntimeError when zero rows produced for a root symbol
# Test: run() raises RuntimeError when zero rows produced across all symbols
# Test: run() continues to next session after data error (other sessions still process)
```

Mock `build_session_chain` for isolation. Use `caplog` or `capfd` pytest fixture to assert warning messages.

---

## Section 6: Smoke-Test Script

### Tests to write first (as assertions within the script itself, not pytest)

The smoke-test is a script with `assert`-style checks. For the pytest harness, test the check helper:

```python
# Test (in test_engine.py): check() prints PASS when condition=True
# Test: check() prints FAIL when condition=False
# Test: check() returns True on pass, False on fail
# Test: main() exits with code 1 when at least one check fails
# Test: main() exits with code 0 when all checks pass (mock build_session_chain)
```

---

## Section 7: Per-Contract Bar Index

### Tests to write first

```python
# Test: _build_contract_bar_index returns dict keyed by contract_name
# Test: each value is a sorted numpy array of bar_close timestamps
# Test: _next_bar_for_contract returns the first bar_close > entry_bar for the contract
# Test: _next_bar_for_contract returns None when no bar exists after entry_bar
# Test: performance regression guard — 10,000 candidates with 100 contracts × 75 bars
#   runs _next_bar_for_contract in < 0.1s total (not a correctness test, a perf guard)
```

---

## Section 8: Unit Tests (already part of the plan)

The unit tests listed in Section 8 of `claude-plan.md` are themselves TDD tests. They are listed here for completeness:

```python
# tests/test_engine.py::test_build_actions_long_bfly_entry
# tests/test_engine.py::test_build_actions_long_bfly_exit
# tests/test_engine.py::test_build_actions_short_bfly_entry
# tests/test_engine.py::test_build_actions_short_bfly_exit
# tests/test_engine.py::test_cashflow_long_bfly_entry_hand_computed
# tests/test_engine.py::test_cashflow_scale_applied
# tests/test_engine.py::test_transaction_cost_uses_4_orders
```

---

## Section 9: Full Run and Output Verification

No automated pytest tests for the full run. The spot-check is manual (see Section 9 of plan). Automated regression can be added in split 03 once a baseline run exists.

The smoke-test script (`scripts/smoke_test_pipeline.py`) serves as the automated gate before the full run.

---

## Test Execution Order

Write and run tests in this order (TDD: test fails first, then implement to pass):

1. `test_build_actions_*` (4 tests) → implement / confirm Section 1
2. `test_cashflow_*` + `test_transaction_cost_uses_4_orders` → implement Section 2
3. `test_fill_leg_with_fallback_*` → implement `_fill_leg_with_fallback`
4. `test_simulate_exit_*` → implement revised `_simulate_exit`
5. `test_build_nav_*` → implement `_build_nav`
6. `test_run_skips_data_error_*` → implement session error handling
7. `test_contract_bar_index_*` → implement `_build_contract_bar_index`
8. Write and run `scripts/smoke_test_pipeline.py`
9. Run full backtest
