# Combined Spec — Split 02: Backtest Engine & End-to-End Run

---

## 1. Objective

Fix the backtest execution engine (`src/essvi_bfly/backtest/engine.py`) and produce honest raw output CSVs from a full January 2026 run on NIFTY + BANKNIFTY, 5-min bars, 1 lot per trade.

**Pre-condition:** Split 01 (signal module corrections — direction logic, edge sign, z-score rolling) is already merged. Split 02 builds on the corrected signal state.

---

## 2. Scope

### In scope:
- Audit and fix `_build_actions()` (entry + exit for both directions)
- Audit and fix `_cashflow_from_fills()` (sign convention, PnL formula)
- Audit and fix `_simulate_exit()` — replace "discard on no fill" with time-stop + lp fallback
- Data pipeline smoke-test script for one session
- Full end-to-end backtest run (January 2026)
- Fix any runtime errors encountered during the run

### Out of scope:
- Performance metrics, Sharpe ratio, drawdown charts (Split 03)
- Signal logic correctness (Split 01, already done)
- NAV scaling or multi-lot sizing

---

## 3. Key Decisions (from interview)

| Decision | Resolution |
|---|---|
| Split 01 status | Already merged; proceed from corrected code |
| `_simulate_exit` no-fill behavior | Replace discard with **time-stop**: force exit at `max_holding_bars` bar |
| Time-stop fallback fill price | Use `lp` (last-traded price) when no valid two-sided quote available |
| Session error handling | **Data-loading errors** (missing file, schema mismatch) → log warning and skip session; **logic errors** → raise immediately |
| Smoke-test output | stdout only — pass/fail assertions, no output files |

---

## 4. Engine Audit Requirements

### 4.1 `_build_actions(candidate, leg_quotes, is_exit)`

Must verify:

| Direction | is_exit | Actions (order matters) |
|---|---|---|
| LONG_BFLY | False | BUY wing_low, SELL body, SELL body, BUY wing_high |
| LONG_BFLY | True | SELL wing_low, BUY body, BUY body, SELL wing_high |
| SHORT_BFLY | False | SELL wing_low, BUY body, BUY body, SELL wing_high |
| SHORT_BFLY | True | BUY wing_low, SELL body, SELL body, BUY wing_high |

Verify: body contract appears twice (2 independent fills at the same price) — correct for 1-lot sizing, cashflow accounts for 2× body.

### 4.2 `_cashflow_from_fills(actions, fills, lot_size, multiplier)`

Sign convention:
- SELL = `+fill.price × scale` (cash inflow)
- BUY = `-fill.price × scale` (cash outflow)

For LONG_BFLY entry:
- wing_low: BUY → −price
- body × 2: SELL, SELL → +2×price  
- wing_high: BUY → −price
- Net entry_cashflow = `−wing_low − wing_high + 2×body` at market prices

Net debit condition for LONG_BFLY: `entry_cashflow < 0` (body overpriced relative to wings).

PnL formula: `pnl = entry_cashflow + exit_cashflow − total_transaction_cost`

### 4.3 `_simulate_exit()` — Time-Stop Addition

**Current behavior:** Iterate `max_holding_bars` bars, return None if no full fill found.

**New behavior:**
1. Primary loop: iterate bars in order, attempt fill at each exit-trigger bar (|z| ≤ exit_z OR |z| ≥ stop_z)
2. If a full fill (all 4 legs) is found in the primary loop, return it.
3. If primary loop exhausts without a fill, execute **time-stop** at the last available bar:
   - Attempt standard `_get_leg_open_quotes` fill at `max_holding_bars` bar
   - If any leg quote is missing or zero: use `lp` (last-traded price) as fallback
   - Record `exit_type = "time_stop"` in output
4. Never return None — every entered trade must have an exit.

### 4.4 Transaction Cost Accounting

Apply costs **at both entry and exit** (4 leg orders per event):
```
entry_cost = 4 × leg_brokerage + |entry_turnover| × (fee_rate + tax_rate)
exit_cost  = 4 × leg_brokerage + |exit_turnover|  × (fee_rate + tax_rate)
total_cost = entry_cost + exit_cost
```

---

## 5. Data Pipeline Smoke-Test

**File:** `scripts/smoke_test_pipeline.py`

**Checks for session `2026_01_02`, symbol `NIFTY`:**
1. `chain` is non-empty (at least 1 row)
2. `tau_years > 0` for all rows
3. `mid > 0` for liquid strikes (ATM ±3% moneyness)
4. `forward` is non-null and within 1% of underlying price
5. `quote_ok` is True for ≥ 50% of rows
6. At least 3 calibration slices converged (`converged == True`)

**Output:** stdout assertions. Exits with code 0 on pass, code 1 on any failure.

**Error handling:** Data-loading errors (missing file) → print error + exit 1. Logic errors (NaN tau, negative mid) → assert + exit 1.

---

## 6. BacktestConfig for the Run

```python
BacktestConfig(
    bar_freq           = "5min",
    root_symbols       = ("NIFTY", "BANKNIFTY"),
    start_date         = None,  # all of January 2026
    end_date           = None,
    max_expiries_per_session = 1,
    entry_z            = 1.5,
    exit_z             = 0.5,
    stop_z             = 3.5,
    persistence_bars_5m = 2,
    holding_bars_5m    = 8,  # 40 min max
    calibration_rmse_limit = 0.02,
    leg_brokerage_per_order = 20.0,
    fee_rate           = 0.0005,
    tax_rate           = 0.0005,
)
```

---

## 7. Expected Outputs

Six CSVs in `outputs/essvi_bfly/reports/`:

| File | Contents |
|---|---|
| `butterfly_chain.csv` | All option bars with iv_essvi, residual_iv, zscore |
| `butterfly_calibration_diagnostics.csv` | Per-slice RMSE, convergence status |
| `butterfly_candidates.csv` | All candidates before simulation (entry signals) |
| `butterfly_fills.csv` | Individual leg fills (4 per trade per side) |
| `butterfly_trades.csv` | One row per trade: entry_bar, exit_bar, entry_zscore, exit_zscore, pnl, exit_type |
| `butterfly_nav.csv` | Cumulative P&L by trade |

---

## 8. Spot-Check Criteria (post-run validation)

For 5 sampled trades from `butterfly_trades.csv`:
- `entry_bar < exit_bar` (chronological order preserved)
- `|entry_zscore| >= entry_z` (1.5)
- PnL sign is plausible:
  - LONG_BFLY profitable trade: `pnl > 0` when `|exit_zscore| < |entry_zscore|`
  - Stopped-out trade: `pnl < 0` and `|exit_zscore| >= stop_z`
- `lot_size × contract_multiplier` is consistent with manifest data

---

## 9. Error Handling Summary

| Failure type | Behavior |
|---|---|
| Missing parquet file | Log warning, skip session |
| Schema mismatch (unexpected columns) | Log warning, skip session |
| Calibration fails all slices | Log warning, skip session (no candidates generated) |
| NaN in cashflow or z-score | Raise immediately — logic error |
| All 21 sessions fail | Raise at end with summary (never silently produce empty CSVs) |
| Logic bugs (divide-by-zero, key error in chain_index) | Raise immediately — no try/except wrapper |
