# Research Findings: Split 02 — Backtest Engine & End-to-End Run

---

## A. Codebase Research

### A1. Project Structure

```
src/essvi_bfly/
├── __init__.py / __main__.py    # Entry point (argparse → run_backtest)
├── config.py                    # BacktestConfig dataclass
├── instruments.py               # load_manifest(), contract name parsing
├── backtest/
│   ├── engine.py                # BacktestEngine (main audit target)
│   ├── event_loop.py            # run_backtest() dispatcher
│   ├── results.py               # write_results() CSV exporter
│   └── straddle_engine.py       # Alternative strategy (not in scope)
├── execution/
│   ├── fills.py                 # fill_leg() → FillResult
│   └── slippage.py              # estimate_transaction_cost()
├── iv/
│   ├── black_scholes.py         # price_option_forward()
│   └── implied_vol.py           # Newton-Raphson IV solver
├── portfolio/
│   └── structures.py            # ButterflyTrade dataclass
├── preprocess/
│   ├── option_chain.py          # build_session_chain() — key audit target
│   ├── bars.py                  # generate_bar_schedule(), sample_state_on_bars()
│   ├── normalize.py             # normalize_market_frame()
│   └── state_reconstruction.py # reconstruct_state_events()
├── signal/
│   ├── candidate_selection.py  # select_candidates(), ButterflyCandidate
│   ├── residuals.py             # calibrate_surface()
│   └── zscores.py              # add_residual_zscores()
└── surface/
    └── calibrate.py / essvi.py  # eSSVI model fit
```

**Dependencies:** numpy, pandas, scipy, pyarrow, pytest.

### A2. BacktestConfig Key Fields (defaults)

| Field | Default | Notes |
|---|---|---|
| `bar_freq` | `"5min"` | |
| `root_symbols` | `("NIFTY","BANKNIFTY")` | |
| `max_expiries_per_session` | 1 | Nearest expiry only |
| `entry_z` | 1.5 | |
| `exit_z` | 0.5 | |
| `stop_z` | 3.5 | |
| `persistence_bars_5m` | 2 | |
| `holding_bars_5m` | 8 | 40 min max |
| `zscore_window_5m` | 75 | Rolling window |
| `calibration_rmse_limit` | 0.02 | 2 vol points |
| `leg_brokerage_per_order` | 20.0 | ₹20/leg/order |
| `fee_rate`, `tax_rate` | 0.0005 each | STT + exchange |
| `risk_free_rate` | 0.06 | Annual |
| `min_edge_to_cost_ratio` | 1.5 | Edge/cost filter |

### A3. Raw Data Schema

**Parquet files** in `data/raw/january_2026/<session_date>/<contract>_<date>.parquet`

Key columns: `timestamp` (IST), `bp1–bp5` / `sp1–sp5` (bid/ask price 5-levels), `bq1–bq5` / `sq1–sq5` (bid/ask qty), `lp` (last price), `v` (volume), `oi` (open interest), `ls` (lot size), `ml` (multiplier), `ft` (feed time UNIX).

**Manifest:** `data/metadata/MANIFEST.csv` — columns: `session_date, folder_date, contract_name, root_symbol, market_family, instrument_type, option_side, strike, expiry_code, expiry_style, exchange_hint, file_name, relative_path, absolute_path`.

### A4. Data Pipeline Flow

```
Raw Parquet
  → normalize_market_frame()       (type coercion)
  → reconstruct_state_events()     (dedup by ft, fwd-fill, age-tag)
  → generate_bar_schedule()        (09:15–15:30 IST, 5-min)
  → sample_state_on_bars()         (backward merge → bar close quotes)
  → sample_state_at_bar_open()     (forward merge → bar open quotes)
  → build_session_chain()          (combine options + underlying + futures)
       computes: tau_years, mid, spread, spread_pct, quote_ok, forward
  → calibrate_surface()            (eSSVI fit → iv_essvi, residual_iv)
  → add_residual_zscores()         (rolling zscore within session)
  → select_candidates()            (z/persistence/edge/cost filters)
  → BacktestEngine._simulate()     (fill entries, simulate exits, compute PnL)
  → write_results()                (6 CSVs)
```

### A5. BacktestEngine Core Methods (as-coded)

#### `_build_actions(candidate, leg_quotes, is_exit: bool) → list[tuple]`

Standard structure (as-coded):
- **LONG_BFLY entry:** BUY wing_low, SELL body×2, BUY wing_high
- **LONG_BFLY exit:** SELL wing_low, BUY body×2, SELL wing_high
- **SHORT_BFLY entry:** SELL wing_low, BUY body×2, SELL wing_high
- **SHORT_BFLY exit:** BUY wing_low, SELL body×2, BUY wing_high

#### `_cashflow_from_fills(actions, fills, lot_size, multiplier) → float`

```python
return sum(
    (fill.price if action == "SELL" else -fill.price) * scale
    for (action, _, _), fill in zip(actions, fills)
)
```

Sign: SELL = +price×scale (inflow), BUY = −price×scale (outflow). 

**Critical:** `pnl = entry_cashflow + exit_cashflow − transaction_cost`
- LONG_BFLY entry: net debit → entry_cashflow is **negative**
- LONG_BFLY exit: net credit → exit_cashflow is **positive**
- Profitable trade: exit_cashflow + entry_cashflow > transaction_cost

#### `_simulate_exit()` — known "discard on no fill"

The exit loop iterates up to `max_holding_bars` bars looking for a bar where all 4 legs can fill. If no such bar exists, the trade is **discarded** (returns None). This is conservative but may filter many trades.

#### `fill_leg(quote_row, action) → FillResult`

- BUY: fills at `sp1` (ask) if `sq1 > 0`
- SELL: fills at `bp1` (bid) if `bq1 > 0`
- Realistic crossing-spread execution.

#### `estimate_transaction_cost(turnover, fee_rate, tax_rate, brokerage, orders)`

```python
return abs(turnover) * (fee_rate + tax_rate) + brokerage * orders
```

### A6. Signal Module

#### Z-Score Rolling Window

Groups by `(contract_name, session_date)` — rolling window **resets between sessions** (correct). Window = `zscore_window_5m` (default 75 bars ≈ 6h15m). Min periods = 20.

#### `select_candidates()` filters (in order)

1. `converged == True AND rmse <= calibration_rmse_limit`
2. Group by `(bar_close, root_symbol, expiry_code, option_side)`, sort by strike
3. For each triplet: equal wing spacing, all three `quote_ok == True`
4. `same_sign_persistence >= persistence_bars`
5. `abs(body.zscore) >= entry_z`
6. OTM check (CE: body ≥ forward, PE: body ≤ forward)
7. All three `iv_essvi` finite
8. Edge/cost filter: `gross_edge > 0` AND `gross_edge > estimated_cost` AND `gross_edge / estimated_cost >= min_edge_to_cost_ratio`

**Known bug flag (from project-manifest):** Direction assignment and edge calculation "likely inverted." This is a Phase 01 concern; Phase 02 assumes Phase 01 is fixed.

### A7. Option Chain: `build_session_chain()`

Computes for each option bar:
- `tau_years = (expiry_dt − bar_close).total_seconds() / (365.25×86400)`
- `mid = (bp1 + sp1) / 2`
- `spread = sp1 − bp1`, `spread_pct = spread / mid`
- `quote_ok = bid > 0 AND ask > 0 AND not crossed AND spread_pct <= max_spread_pct AND has_size`
- `forward`: from futures basis if available, else `spot × e^{(r−carry)×tau}`

### A8. Testing (`tests/test_signal.py`)

**Framework:** pytest

8 tests exist covering:
- `_build_actions` direction convention (LONG_BFLY vs SHORT_BFLY)
- Persistence counter sign-flip and leading NaN
- Rolling zscore within-session boundary
- Direction assignment from zscore sign
- Edge sign for both directions

**Gaps:** No tests for `_cashflow_from_fills`, no tests for `_simulate_exit`, no integration test for `build_session_chain`.

---

## B. Web Research

### B1. eSSVI Calibration

**Model:** Extended SSVI (Hendriks & Martini 2017, SSRN 2971502). Relaxes SSVI's global-ρ constraint; each maturity slice gets own ρ(θ). Retains closed-form no-arbitrage conditions.

**No-arbitrage conditions:**
- Butterfly: `θ·φ·(1+|ρ|) < 4` and `θ·φ²·(1+|ρ|) ≤ 4`
- Calendar-spread: `∂_t w(k,t) ≥ 0` — total variance non-decreasing in time

**Calibration RMSE thresholds (practitioner):**
- Accepted fit = model price within bid-ask spread for liquid strikes
- Good fit for liquid index options ≲ 1 vol point (100 bps IV) absolute error
- `calibration_rmse_limit = 0.02` (2 vol points) in BacktestConfig is conservative; 0.01 is tighter

**Common pitfalls:**
1. Short-maturity slices: fix ρ or constrain near prior slice
2. Corrupted ATM anchor (crossed/zero bid): pre-filter before calibrating
3. Fitting to mid-price on illiquid wings: weight down or exclude zero-bid strikes
4. Using spot moneyness instead of forward moneyness: always use `k = ln(K/F)`

### B2. Butterfly Spread Conventions

**Standard 1-2-1 structure:**
- Long butterfly = BUY 1 wing_low, SELL 2 body, BUY 1 wing_high
- Equal wing spacing is required: `K_mid − K_lo = K_hi − K_mid`

**PnL:**
- Net debit at entry: `D = ask_low − 2×bid_mid + ask_hi` (realistic)
- Max profit at expiry: `Δ − D` (where Δ = wing width)
- Max loss: `D` (net debit paid)

**Entry/exit fill conventions:**
- Long legs (BUY): fill at ask
- Short legs (SELL): fill at bid
- ORATS data: slippage ≈ 56% of bid-ask width for 4-leg structures

### B3. Cashflow & PnL Sign Convention

**Convention A (used in this codebase — cash ledger):**
```
entry_cashflow = −net_debit      (negative for long butterfly)
exit_cashflow  = +exit_spread    (positive when closing long butterfly)
pnl = entry_cashflow + exit_cashflow − transaction_cost
```

**Transaction costs — apply at BOTH entry and exit:**
```
entry_cost = 4 × leg_brokerage + |entry_turnover| × (fee_rate + tax_rate)
exit_cost  = 4 × leg_brokerage + |exit_turnover|  × (fee_rate + tax_rate)
total_cost = entry_cost + exit_cost
```

Common mistake: deducting cost only once (at exit), halving the realistic impact.

### B4. Options Chain Data Pipeline

**Tau computation (best practice for intraday):**
```python
tau = (expiry_dt - bar_close_dt).total_seconds() / (365.25 * 86400)
# Use calendar-seconds precision for intraday bars (especially <1 week to expiry)
```

**Quote quality filters (in order):**
1. `bid > 0` (zero-bid = illiquid/worthless)
2. `ask > bid` (no crossed/locked markets)
3. `spread_pct <= max_spread_pct` (e.g., 12% for NSE)
4. `open_interest > 0` (optionally)
5. Quote age filter (stale if unchanged for many bars)

**Forward from put-call parity:**
```python
# Use strike nearest to ATM (lowest |C_mid − P_mid|)
F = exp(r * tau) * (C_atm_mid − P_atm_mid) + K_atm
```
Cross-check against futures price; if deviation > 0.1%, flag for data quality.

**NSE-specific:** Futures price is the most direct `F` observation. Use PCF parity as cross-check only.

---

## C. Testing Context

**Existing framework:** pytest in `tests/`

**Test gaps for Phase 02:**
- `_cashflow_from_fills` — no test (critical: sign correctness)
- `_simulate_exit` — no test (critical: discard behavior, stop logic)
- `build_session_chain` integration — no test

**Recommended test patterns for new tests:**
- Synthetic DataFrames with known prices → verify cashflow signs exactly
- Controlled zscore sequences → verify exit triggers (profit-take vs stop)
- Single-session parquet fixture → verify tau > 0, mid > 0, forward ≈ spot

**Running tests:**
```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run pytest tests/ -v
```
