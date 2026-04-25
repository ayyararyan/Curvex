<!-- SPLIT_MANIFEST
01-signal-audit-fix
02-backtest-engine-run
03-reporting-analysis
END_MANIFEST -->

# Project Manifest — eSSVI Butterfly Volatility Arbitrage

## Overview

This project implements and validates an intraday butterfly statistical arbitrage strategy on NSE index options (NIFTY + BANKNIFTY), using the eSSVI implied-volatility surface as a fair-value model. The core signal: when the market butterfly premium deviates from the eSSVI-implied butterfly premium by more than a z-score threshold, enter a butterfly spread that profits from mean reversion.

The existing `src/essvi_bfly/` package has all the right modules in place but contains logic bugs that need to be found and fixed before a trustworthy backtest can be run. Work proceeds in three sequential phases.

---

## Splits

### 01 — Signal Audit & Fix
**Purpose:** Make the signal pipeline correct.

The central bug suspect is `signal/candidate_selection.py` — the direction assignment (`LONG_BFLY` vs `SHORT_BFLY`) and the edge calculation likely have a sign inversion relative to the strategy doc and standard butterfly conventions. The rolling z-score window may also span session boundaries (contaminating signal with prior-day state).

Scope:
- Formally audit the z-score sign convention: positive residual (market IV > eSSVI IV at body) → which butterfly direction profits?
- Fix direction assignment and edge formula in `candidate_selection.py`
- Check `zscores.py` rolling window — clip to within-session data only
- Verify persistence counter counts consecutive same-sign bars correctly
- Add unit tests for signal module (signal direction, z-score formula, persistence)

Inputs: `src/essvi_bfly/signal/`, `eSSVI Butterfly Stat-Arb Strategy.md`
Outputs: corrected signal module, passing unit tests

---

### 02 — Backtest Engine & End-to-End Run
**Purpose:** Get the pipeline running on real January 2026 data and produce honest output.

Scope:
- Audit `backtest/engine.py` `_build_actions`: verify LONG_BFLY vs SHORT_BFLY leg directions
- Audit cashflow computation (`_cashflow_from_fills`): verify sign convention (buy = negative cash, sell = positive cash)
- Audit exit simulation (`_simulate_exit`): verify time stop (≤ max_holding_bars), vol stop (|z| ≥ stop_z), and fill availability
- Smoke-test data pipeline: parquet → state reconstruction → 5-min bars → option chain (verify forward, tau, mid, spread columns are non-null for liquid strikes)
- Run end-to-end backtest: NIFTY + BANKNIFTY, 5-min bars, January 2026, 1 lot per trade
- Produce raw output CSVs: `chain`, `calibration_diagnostics`, `candidates`, `fills`, `trades`, `nav`

Depends on: 01 (correct signal module)
Inputs: corrected signal module, `data/raw/january_2026/`, `data/metadata/`
Outputs: raw output CSVs in `outputs/essvi_bfly/reports/`

---

### 03 — Reporting & Analysis
**Purpose:** Turn raw output into interpretable results.

Scope:
- Validate trade CSV: correct P&L per trade, no duplicate trade IDs, entry/exit bar pairs make sense
- Generate cumulative P&L / NAV curve (matplotlib, saved to `outputs/essvi_bfly/reports/`)
- Generate calibration diagnostics report: RMSE time-series per expiry, convergence rate per session
- Compute summary statistics: Sharpe ratio, max drawdown, win rate, average holding bars, total turnover
- Write brief markdown performance summary at `outputs/essvi_bfly/reports/performance_summary.md`

Depends on: 02 (raw output CSVs)
Inputs: CSVs from split 02
Outputs: charts, performance summary markdown

---

## Execution Order

```
01-signal-audit-fix
        │
        ▼
02-backtest-engine-run
        │
        ▼
03-reporting-analysis
```

All three are sequential. There is no parallelism — each split's correctness depends on the previous.

---

## Cross-Cutting Concerns

- **Data:** January 2026 only (NIFTY + BANKNIFTY). Located at `data/raw/january_2026/`. Manifest at `data/metadata/MANIFEST.csv`.
- **Bar frequency:** 5-minute throughout.
- **Config:** `BacktestConfig` in `src/essvi_bfly/config.py` is the single source of truth for all parameters.
- **Sizing:** 1 lot per trade (no NAV-scaling in backtest).
- **Costs:** 4 legs × half-spread + brokerage per butterfly. `config.leg_brokerage_per_order = 20.0` and `config.fee_rate = 0.0005`.

---

## /deep-plan Commands

Once splits are confirmed:

```bash
/deep-plan @01-signal-audit-fix/spec.md
/deep-plan @02-backtest-engine-run/spec.md
/deep-plan @03-reporting-analysis/spec.md
```
