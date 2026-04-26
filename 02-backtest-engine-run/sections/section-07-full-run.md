# Section 07: Full Run and Output Verification

## Overview

Final integration step. All engine fixes and additions from sections 01–06 must be complete and `uv run pytest tests/ -v` must pass with zero failures before starting. This section runs the full 21-session backtest and manually spot-checks the output.

No code changes are made here. If runtime errors surface during the run, diagnose and fix in the relevant earlier section.

**Depends on:** sections 01, 02, 03, 04, 05, 06  
**Blocks:** nothing (final)

---

## Pre-Flight Gate

Run the smoke-test for at least one session before the full run:

```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run python scripts/smoke_test_pipeline.py --session 2026_01_02 --symbol NIFTY
```

All 11 checks must pass (exit code 0). If any fail, return to the relevant section.

Also confirm all tests pass:
```bash
uv run pytest tests/ -v -k "not slow"
```

---

## Run Configuration

These are the canonical Split 02 parameters — do not deviate:

```
bar_freq                    = "5min"
root_symbols                = ("NIFTY", "BANKNIFTY")
start_date                  = None          # all January 2026
end_date                    = None
max_expiries_per_session    = 1
entry_z                     = 1.5
exit_z                      = 0.5
stop_z                      = 3.5
persistence_bars_5m         = 2
holding_bars_5m             = 8
calibration_rmse_limit      = 0.02
leg_brokerage_per_order     = 20.0
fee_rate                    = 0.0005
tax_rate                    = 0.0005
```

---

## Run Command

```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run python scripts/run_backtest.py \
  --strategy butterfly \
  --bar-freq 5min \
  --root-symbol NIFTY \
  --root-symbol BANKNIFTY
```

**Output overwrite policy:** Writes to `outputs/essvi_bfly/reports/` — existing files are overwritten. Back up prior outputs manually if needed. A `--run-tag` subdirectory option will be added in Split 03.

The run must complete without unhandled exceptions. Session-level data errors are logged as warnings and skipped (section-04). Logic errors must surface and be fixed — do not suppress with try/except.

---

## Expected Output CSVs

All six must exist in `outputs/essvi_bfly/reports/` with at least one data row each:

| File | Required columns |
|---|---|
| `butterfly_chain.csv` | `bar_close`, `contract_name`, `iv_essvi`, `residual_iv`, `zscore`, `quote_ok` |
| `butterfly_calibration_diagnostics.csv` | `bar_close`, `root_symbol`, `expiry_code`, `rmse`, `converged` |
| `butterfly_candidates.csv` | `bar_close`, `direction`, `body_contract`, `theoretical_edge`, `estimated_cost` |
| `butterfly_fills.csv` | `trade_id`, `leg_index`, `action`, `contract_name`, `fill_price`, `fill_reason` |
| `butterfly_trades.csv` | `trade_id`, `entry_bar`, `exit_bar`, `direction`, `entry_zscore`, `exit_zscore`, `pnl`, `exit_type`, `exit_fill_quality` |
| `butterfly_nav.csv` | `trade_id`, `pnl`, `cumulative_pnl` |

---

## Calibration Summary (Print Before Spot-Check)

Load `butterfly_calibration_diagnostics.csv` and print:
- Per-symbol convergence rate: `(converged == True).sum() / len(df)` per `root_symbol`
- RMSE distribution: median and 95th percentile of `rmse` per symbol

If convergence rate < 50% for a symbol, identify the cause (bad forward, tau near zero, insufficient ATM quotes) before proceeding. A thin candidate pool from poor calibration makes the spot-check uninformative.

---

## Manual Spot-Check: 5 Trades

Sample 5 trades from `butterfly_trades.csv`, aiming for at least one `profit_take`, one `stop_loss`, and one `time_stop` exit if present.

For each trade, verify all six criteria:

**1. Chronological integrity:** `entry_bar < exit_bar`

**2. Entry threshold respected:** `|entry_zscore| >= 1.5`

**3. Gross cashflow positive (profitable trades):** For `pnl > 0` trades, verify `entry_cashflow + exit_cashflow > 0`. Cross-reference fills in `butterfly_fills.csv`.

**4. Stop-loss threshold:** For `exit_type == "stop_loss"` trades, verify `|exit_zscore| >= 3.5`.

**5. Lot-size scaling consistency:** Look up `body_contract` in the manifest for `lot_size` and `contract_multiplier`. Verify `pnl` magnitude is consistent with lot-scale — divide `pnl` by fill price difference and lot size; should be close to an integer multiple.

**6. LONG_BFLY entry sign:** For `direction == "LONG_BFLY"` trades, check that the entry fills show SELL actions on body and BUY on wings. Verify `2 × body_fill_price > wing_low_fill_price + wing_high_fill_price` (body was genuinely overpriced at entry). If this inequality fails for every LONG_BFLY in the sample, the z-score direction logic may be inverted — raise this as a regression of Split 01.

If any criterion fails on any trade, diagnose the root cause before declaring this section complete. Do not dismiss failures as outliers.

---

## Acceptance Criteria

- [ ] All 6 CSVs exist in `outputs/essvi_bfly/reports/` with at least 1 data row each
- [ ] `butterfly_trades.csv` contains `exit_type` and `exit_fill_quality` columns
- [ ] `butterfly_nav.csv` contains `cumulative_pnl` column
- [ ] Calibration summary printed; per-symbol convergence rate noted
- [ ] 5 trades manually spot-checked; all 6 criteria verified for each
- [ ] No unhandled exceptions during the run
