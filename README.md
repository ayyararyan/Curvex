# Curvex

Curvex is a research backtest repository for an intraday eSSVI butterfly volatility arbitrage strategy on NSE index options. The current package focuses on NIFTY and BANKNIFTY January 2026 option parquet data, reconstructs sparse quote state into bar-level option chains, fits eSSVI implied-volatility slices, generates residual signals, and simulates butterfly or straddle trades with simple execution and transaction-cost assumptions.

This is a research codebase, not a live-trading system.

## Strategy Overview

The core butterfly strategy compares the observed market butterfly premium against the premium implied by an eSSVI volatility surface.

For each liquid option slice:

1. Reconstruct bid/ask and trade state from sparse parquet updates.
2. Sample instrument state onto 1-minute or 5-minute bars.
3. Build an option chain with spot or futures-based forward estimates.
4. Invert option mids into market implied volatility.
5. Calibrate an eSSVI surface per bar, root symbol, and expiry.
6. Compute residual IV as `market IV - eSSVI IV`.
7. Convert residuals into within-session rolling z-scores.
8. Select same-side, equally spaced butterfly structures whose edge clears estimated costs.
9. Simulate entry on the next bar, exit on mean reversion, stop, or max holding period.
10. Write raw chain, diagnostics, candidates, fills, trades, and NAV/PnL CSVs.

The implemented butterfly direction convention is:

- `LONG_BFLY`: buy low wing, sell 2x body, buy high wing. Used when the body is rich versus model (`zscore >= entry_z`).
- `SHORT_BFLY`: sell low wing, buy 2x body, sell high wing. Used when the body is cheap versus model (`zscore <= -entry_z`).

## Repository Layout

```text
curvex/
  README.md
  pyproject.toml
  uv.lock
  project-manifest.md
  eSSVI Butterfly Stat-Arb Strategy.md
  scripts/
    run_backtest.py
  src/
    essvi_bfly/
      config.py
      instruments.py
      io/
      preprocess/
      iv/
      surface/
      signal/
      execution/
      portfolio/
      backtest/
  tests/
    test_signal.py
  docs/
    essvi_butterfly_backtest/
  01-signal-audit-fix/
  02-backtest-engine-run/
  03-reporting-analysis/
```

Important paths:

- `src/essvi_bfly/config.py`: central `BacktestConfig` for data paths, symbols, thresholds, costs, holding periods, and output directories.
- `src/essvi_bfly/preprocess/`: sparse event normalization, state reconstruction, bar sampling, and option-chain construction.
- `src/essvi_bfly/iv/`: Black-Scholes forward pricer and implied-volatility solver.
- `src/essvi_bfly/surface/`: eSSVI formula, calibration, and diagnostics.
- `src/essvi_bfly/signal/`: residuals, z-scores, butterfly candidate selection, and straddle candidate selection.
- `src/essvi_bfly/backtest/`: butterfly and straddle backtest engines plus CSV result writing.
- `tests/test_signal.py`: regression tests for signal direction, z-score session boundaries, persistence, and butterfly action conventions.
- `docs/essvi_butterfly_backtest/`: implementation notes that translate the strategy document into a build plan.
- `01-signal-audit-fix/`, `02-backtest-engine-run/`, `03-reporting-analysis/`: staged research and execution plans.

## Data Contract

Raw market data and generated outputs are intentionally ignored by git.

Expected local data layout:

```text
data/
  metadata/
    MANIFEST.csv
    CONTRACTS_INVENTORY.csv
  raw/
    january_2026/
      ...
outputs/
  essvi_bfly/
    intermediate/
    reports/
```

`MANIFEST.csv` is expected to describe each contract/session file and include fields such as session date, contract name, root symbol, instrument type, expiry code, strike, and relative path. The loader resolves manifest paths relative to `data/raw/january_2026/`.

The default `BacktestConfig` currently points to the local research workspace path:

```text
/Volumes/One Touch/NSE/onesec/curvex
```

If you clone the repository elsewhere, either update `BacktestConfig` defaults or instantiate `BacktestConfig` with explicit `repo_root`, `data_dir`, `manifest_path`, `inventory_path`, `raw_dir`, and `outputs_dir` values.

## Installation

Python 3.11 or newer is required.

Using `uv`:

```bash
uv sync --dev
```

Using `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install pytest
```

Runtime dependencies are:

- `numpy`
- `pandas`
- `scipy`
- `pyarrow`

The dev dependency is:

- `pytest`

## Running Tests

```bash
uv run pytest
```

or, if using a manually activated virtual environment:

```bash
python -m pytest
```

The current test suite focuses on signal correctness:

- Long and short butterfly direction mapping.
- Positive theoretical edge for selected structures.
- Z-score rolling windows resetting at session boundaries.
- Same-sign persistence counters.
- Butterfly entry action conventions.

## Running A Backtest

Default butterfly run:

```bash
uv run python scripts/run_backtest.py
```

Equivalent module entry point:

```bash
uv run python -m essvi_bfly
```

Useful arguments:

```bash
uv run python scripts/run_backtest.py \
  --strategy butterfly \
  --root-symbol NIFTY \
  --root-symbol BANKNIFTY \
  --start-date 2026_01_01 \
  --end-date 2026_01_31 \
  --bar-freq 5min \
  --max-expiries 1
```

Straddle research path:

```bash
uv run python scripts/run_backtest.py --strategy straddle
```

Supported CLI options:

- `--strategy`: `butterfly` or `straddle`.
- `--root-symbol`: repeatable; defaults to `NIFTY` and `BANKNIFTY`.
- `--start-date`: optional session start filter.
- `--end-date`: optional session end filter.
- `--bar-freq`: `1min` or `5min`; defaults to `5min`.
- `--max-expiries`: maximum expiries processed per session; defaults to `1`.

## Outputs

Backtest CSVs are written under:

```text
outputs/essvi_bfly/reports/
```

For the butterfly strategy, expected report files are:

- `butterfly_chain.csv`: bar-level enriched option chain with IV, eSSVI, residual, z-score, and quality fields.
- `butterfly_calibration_diagnostics.csv`: convergence and fit diagnostics per calibrated slice.
- `butterfly_candidates.csv`: selected structures that pass signal, persistence, calibration, quote-quality, and edge filters.
- `butterfly_fills.csv`: simulated entry and exit fills for each leg.
- `butterfly_trades.csv`: trade-level structure metadata and entry/exit state.
- `butterfly_nav.csv`: trade-level cashflows, transaction costs, and PnL.

For the straddle strategy, the prefix is `straddle_` and the engine writes straddle-specific chain, candidate, trade, fill, and NAV outputs.

## Configuration Highlights

The main parameters live in `BacktestConfig`:

- Universe: `root_symbols=("NIFTY", "BANKNIFTY")`
- Bar frequency: `bar_freq="5min"`
- Calibration quality: `calibration_rmse_limit=0.02`, `min_slice_strikes=3`
- Signal threshold: `entry_z=1.5`
- Exit threshold: `exit_z=0.5`
- Stop threshold: `stop_z=3.5`
- Holding period: `holding_bars_5m=8`, `holding_bars_1m=20`
- Rolling z-score windows: `zscore_window_5m=75`, `zscore_window_1m=375`
- Costs: `leg_brokerage_per_order=20.0`, `fee_rate=0.0005`, `tax_rate=0.0005`
- Liquidity filters: quote age, quote size, max spread percentage, and minimum premium
- Sizing: one lot per trade through lot size and contract multiplier fields

## Research Status

Completed or represented in the current repository:

- Project-level strategy specification and split manifest.
- Implementation plan for sparse parquet data reconstruction through reporting.
- Python package skeleton and working modules for ingestion, features, IV, eSSVI, signals, execution, portfolio accounting, and backtesting.
- Signal audit fixes for butterfly direction and within-session z-score rolling.
- Unit tests for the signal and action convention regressions.

Still data-dependent:

- Full January 2026 end-to-end backtest run.
- Performance summary generation from produced reports.
- Calibration failure analysis across all sessions and expiries.
- Robustness checks around costs, z-score thresholds, holding periods, and liquidity filters.

## Development Notes

Before committing, run:

```bash
uv run pytest
git status --short
```

The repository ignores:

- `data/`
- `outputs/`
- `.venv/`
- Python build and cache artifacts
- macOS resource-fork files such as `._*`

Do not commit raw market data, generated reports, local virtual environments, or local agent/tooling state.

## Disclaimer

This repository is for research and engineering validation only. It does not provide investment advice, execution advice, or a production-ready trading system.
