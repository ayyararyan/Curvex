# Split 03 — Reporting & Analysis

## Goal

Turn the raw backtest output CSVs into interpretable results: a P&L/NAV curve, calibration diagnostics report, summary statistics, and a brief markdown performance summary.

## Context

**Input CSVs (from split 02):** located at `/Volumes/One Touch/NSE/onesec/curvex/outputs/essvi_bfly/reports/`
- `butterfly_trades.csv` — per-trade entry/exit/pnl
- `butterfly_nav.csv` — per-trade entry_bar, exit_bar, cashflows, transaction_cost, pnl
- `butterfly_calibration_diagnostics.csv` — per-bar eSSVI RMSE and convergence
- `butterfly_candidates.csv` — all candidate butterflies evaluated (including rejected ones)
- `butterfly_fills.csv` — per-leg fill prices

**Output directory:** `/Volumes/One Touch/NSE/onesec/curvex/outputs/essvi_bfly/reports/`

**Depends on:** split 02 (raw output CSVs must exist and be trustworthy).

## Tasks

### 1. Trade-Level CSV Validation

Before generating charts, verify the trade data is internally consistent:
- `entry_bar < exit_bar` for all trades
- `pnl = entry_cashflow + exit_cashflow - transaction_cost` (within floating-point tolerance)
- No duplicate `trade_id` values
- `entry_zscore` column: all values `|z| >= config.entry_z` (1.5)
- Report: count of trades, NIFTY vs BANKNIFTY split, LONG_BFLY vs SHORT_BFLY split

### 2. Cumulative P&L / NAV Curve

Write `src/essvi_bfly/backtest/results.py` or a new `scripts/plot_results.py` that:
- Loads `butterfly_nav.csv`
- Constructs a daily cumulative P&L series (sum of `pnl` by `exit_bar.date`)
- Plots cumulative P&L on a line chart with:
  - X-axis: calendar date (January 2026)
  - Y-axis: cumulative P&L in ₹
  - Title: "eSSVI Butterfly Stat-Arb — January 2026 Cumulative P&L"
  - Shaded drawdown regions
- Saves to `outputs/essvi_bfly/reports/pnl_curve.png`

### 3. Calibration Diagnostics Report

From `butterfly_calibration_diagnostics.csv`:
- Plot RMSE time-series (5-min bars on x-axis, vol-point RMSE on y-axis) for each root_symbol × expiry_code pair
- Compute: convergence rate per session (% of bars where eSSVI converged), median RMSE
- Flag sessions where convergence rate < 80% (poor calibration days)
- Save chart to `outputs/essvi_bfly/reports/calibration_diagnostics.png`

### 4. Summary Statistics

Compute from `butterfly_nav.csv` and `butterfly_trades.csv`:

| Metric | Formula |
|---|---|
| Total trades | count of closed trades |
| Win rate | trades where pnl > 0 / total |
| Gross P&L | sum(pnl) |
| Net P&L (after costs) | sum(pnl) (already net in the engine) |
| Avg trade P&L | mean(pnl) |
| Avg holding bars | mean(exit_bar - entry_bar in bars) |
| Max drawdown | max drawdown of cumulative P&L curve |
| Sharpe (annualized) | mean(daily_pnl) / std(daily_pnl) × sqrt(252) |
| Total turnover | sum(transaction_cost) |

Report NIFTY and BANKNIFTY separately.

### 5. Markdown Performance Summary

Write `outputs/essvi_bfly/reports/performance_summary.md` with:
- Strategy description (one paragraph)
- Data period and universe
- Summary statistics table (from task 4)
- Key observations (2–3 bullet points): e.g., which symbol had better signal quality, calibration reliability, avg holding period vs max_holding_bars
- Known caveats: 1-lot sizing, no delta hedging, no intraday liquidity constraints beyond spread filter

## What This Split Does NOT Cover

- Signal logic or engine fixes (splits 01 and 02)
- Strategy extensions (broken-wing butterfly, diagonal spreads, etc.)

## Outputs / Deliverables

1. `outputs/essvi_bfly/reports/pnl_curve.png`
2. `outputs/essvi_bfly/reports/calibration_diagnostics.png`
3. `outputs/essvi_bfly/reports/performance_summary.md`
4. Updated `src/essvi_bfly/backtest/results.py` or new `scripts/plot_results.py` containing the chart generation code

## Dependencies

- **Needs:** Raw output CSVs from split 02
- **Provides:** Final deliverables — charts, summary, performance report
