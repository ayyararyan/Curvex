# Split 02 — Backtest Engine & End-to-End Run

## Goal

Fix the backtest execution engine and produce honest raw output from a full run on January 2026 data (NIFTY + BANKNIFTY, 5-min bars, 1 lot per trade).

## Context

**Package root:** `/Volumes/One Touch/NSE/onesec/curvex/src/essvi_bfly/`
**Data:** `/Volumes/One Touch/NSE/onesec/curvex/data/raw/january_2026/` (21 session dates)
**Manifest:** `/Volumes/One Touch/NSE/onesec/curvex/data/metadata/MANIFEST.csv`
**Config:** `src/essvi_bfly/config.py` — `BacktestConfig` dataclass (all parameters)
**Entry point:** `scripts/run_backtest.py` → `essvi_bfly.__main__.main()` → `backtest/event_loop.py`

**Depends on:** split 01 (corrected signal module) must be applied first.

## Known Suspect Areas

### 1. `_build_actions` in `backtest/engine.py`

```python
# LONG_BFLY entry (as written):
("BUY", candidate.wing_low_contract, low),
("SELL", candidate.body_contract, body),
("SELL", candidate.body_contract, body),   # body listed twice
("BUY", candidate.wing_high_contract, high),
```

- Standard long butterfly = BUY 1 wing-low, SELL 2 body, BUY 1 wing-high. The above looks correct structurally.
- Verify: the `fill_leg` function is called on the same `body` row twice (two independent fills at the same price). This is fine for 1-lot sizing but confirm the cashflow math accounts for 2 body fills.

Verify `SHORT_BFLY` entry actions are the exact reverse.

### 2. Cashflow Computation

In `_cashflow_from_fills`:
```python
(fill.price if action == "SELL" else -fill.price) * scale
```
- SELL = receive cash (positive), BUY = pay cash (negative). This sign convention is correct.
- Verify: at exit, the roles reverse (LONG_BFLY exits by selling wings + buying back body). Confirm `_build_actions(is_exit=True)` correctly reverses all actions.
- Verify: entry cashflow (net debit for LONG_BFLY, net credit for SHORT_BFLY) has the correct sign so that `pnl = entry_cashflow + exit_cashflow - transaction_cost` is positive for a profitable trade.

### 3. Exit Simulation

In `_simulate_exit`:
- The function iterates the `max_holding_bars` rows after entry for the body contract.
- Exit triggers: `|z| <= exit_z` (signal reverted) OR `|z| >= stop_z` (vol stop).
- The exit uses `_get_leg_open_quotes` — i.e., it fills at the OPEN of the exit bar (not the close). Verify this is intentional and document it.
- If all `max_holding_bars` rows are iterated without a successful fill, the trade is discarded (`return None`). This may filter out too many trades; consider whether a time-stop exit at market (use whatever quote is available) is more realistic.

### 4. Data Pipeline Smoke-Test

Before running the full backtest, verify the data pipeline produces sensible option chain data for one session:

```python
from essvi_bfly.instruments import load_manifest
from essvi_bfly.preprocess.option_chain import build_session_chain
from essvi_bfly.config import BacktestConfig

config = BacktestConfig()
manifest = load_manifest(config.manifest_path)
artifacts = build_session_chain(manifest, "2026_01_02", "NIFTY", config)
chain = artifacts.option_bars
```

Check:
- `chain` is non-empty
- `tau_years > 0` for all rows
- `mid > 0` for liquid strikes (ATM ± 3%)
- `forward` is non-null and close to spot
- `quote_ok` is True for at least 50% of rows

### 5. Configuration for the Run

Ensure `BacktestConfig` is set correctly for a clean 1-lot run:

- `bar_freq = "5min"`
- `root_symbols = ("NIFTY", "BANKNIFTY")`
- `start_date = None, end_date = None` (run all of January 2026)
- `max_expiries_per_session = 1` (nearest expiry only — reduces calibration burden)
- `entry_z = 1.5, exit_z = 0.5, stop_z = 3.5`
- `persistence_bars_5m = 2`
- `max_holding_bars_5m = 8` (40 minutes maximum per trade)
- `calibration_rmse_limit = 0.02` (2 vol points; reject if eSSVI fit is poor)
- `leg_brokerage_per_order = 20.0` (₹20 per leg per order)
- `fee_rate = 0.0005, tax_rate = 0.0005`

No NAV-scaling: 1 lot per trade. The `lot_size` and `contract_multiplier` fields come from the manifest.

### 6. End-to-End Run

Run the full backtest:
```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run python scripts/run_backtest.py --strategy butterfly --bar-freq 5min --root-symbol NIFTY --root-symbol BANKNIFTY
```

The run should produce in `outputs/essvi_bfly/reports/`:
- `butterfly_chain.csv`
- `butterfly_calibration_diagnostics.csv`
- `butterfly_candidates.csv`
- `butterfly_fills.csv`
- `butterfly_trades.csv`
- `butterfly_nav.csv`

If the run errors, fix root cause. Do not skip errors with try/except wrappers.

## Tasks

1. Audit `_build_actions` (entry + exit for both LONG_BFLY and SHORT_BFLY)
2. Audit `_cashflow_from_fills` sign convention and verify `pnl` formula
3. Audit exit simulation — document or fix the "discard on no fill" behavior
4. Run data pipeline smoke-test for one session, fix any issues found
5. Run full backtest; fix any runtime errors
6. Spot-check 5 trades from `butterfly_trades.csv` manually: confirm entry bar < exit bar, |entry_zscore| > entry_z, pnl signs are plausible

## What This Split Does NOT Cover

- Charts and performance metrics (split 03)
- Signal logic correctness (split 01)

## Outputs / Deliverables

1. Fixed `backtest/engine.py` (with audit notes in git commit message)
2. Six output CSVs in `outputs/essvi_bfly/reports/`
3. Brief smoke-test script at `scripts/smoke_test_pipeline.py`

## Dependencies

- **Needs:** Corrected signal module from split 01
- **Provides:** Raw output CSVs consumed by split 03
