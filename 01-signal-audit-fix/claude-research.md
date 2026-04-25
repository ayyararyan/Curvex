# Research Findings — Signal Audit & Fix (Split 01)

## 1. Codebase Findings

### 1.1 Project Structure Summary

```
src/essvi_bfly/
├── config.py                  BacktestConfig dataclass (all thresholds/windows)
├── signal/
│   ├── candidate_selection.py  Direction assignment, edge calc ← primary suspect
│   ├── zscores.py              Rolling z-score + persistence counter
│   └── residuals.py            Market IV inference, eSSVI residual
├── surface/
│   ├── calibrate.py            SSVI fit (theta, rho, psi)
│   └── essvi.py                total_variance_ssvi, implied_vol_ssvi
├── backtest/
│   └── engine.py               _build_actions, _simulate, run()
├── execution/fills.py          fill_leg (BUY at ask, SELL at bid)
└── portfolio/structures.py     ButterflyTrade, TradeLeg dataclasses
```

No `tests/` directory exists. No test framework is declared in `pyproject.toml`.

Dependencies: `numpy`, `pandas`, `scipy`, `pyarrow` (Python ≥ 3.11).

---

### 1.2 Key Code: Direction Assignment (`signal/candidate_selection.py`, lines 73–78)

```python
if body["zscore"] < 0:
    direction = "SHORT_BFLY"
    edge = market_premium - model_premium
else:
    direction = "LONG_BFLY"
    edge = model_premium - market_premium
```

Both `market_premium` and `model_premium` use the butterfly formula:
`value = low - 2 * body + high`  (in price units)

Model premium uses `iv_essvi`-priced legs via `price_option_forward(...)`.

---

### 1.3 Key Code: `_build_actions` (`backtest/engine.py`, lines 242–270)

```python
def _build_actions(self, candidate, leg_quotes, is_exit: bool):
    low, body, high = leg_quotes
    if candidate.direction == "LONG_BFLY":
        if not is_exit:
            return [
                ("BUY",  candidate.wing_low_contract,  low),
                ("SELL", candidate.body_contract,       body),
                ("SELL", candidate.body_contract,       body),
                ("BUY",  candidate.wing_high_contract,  high),
            ]
        # exit: reverse
        return [("SELL", wing_low), ("BUY", body), ("BUY", body), ("SELL", wing_high)]
    # SHORT_BFLY entry:
    if not is_exit:
        return [
            ("SELL", candidate.wing_low_contract,  low),
            ("BUY",  candidate.body_contract,       body),
            ("BUY",  candidate.body_contract,       body),
            ("SELL", candidate.wing_high_contract,  high),
        ]
    # exit: reverse
    return [("BUY", wing_low), ("SELL", body), ("SELL", body), ("BUY", wing_high)]
```

LONG_BFLY entry = BUY wings, SELL body × 2 → **standard long butterfly definition** ✓  
SHORT_BFLY entry = SELL wings, BUY body × 2 → **standard short butterfly definition** ✓

---

### 1.4 Key Code: Rolling Z-Score (`signal/zscores.py`, lines 9–16)

```python
def add_residual_zscores(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = chain.sort_values(["contract_name", "bar_close"]).copy()
    window = config.zscore_window
    grouped = out.groupby("contract_name", group_keys=False)["residual_iv"]
    min_periods = min(20, window)
    out["residual_mean_roll"] = grouped.transform(
        lambda s: s.rolling(window, min_periods=min_periods).mean()
    )
    out["residual_std_roll"] = grouped.transform(
        lambda s: s.rolling(window, min_periods=min_periods).std()
    )
    out["zscore"] = (out["residual_iv"] - out["residual_mean_roll"]) / out["residual_std_roll"]
```

**BUG:** Groups by `contract_name` only. The rolling window carries across session boundaries.
With `zscore_window_5m = 75` bars at 5-min frequency = 6.25 hours (spans the prior session's close).
The trading day is also ~75 bars (9:15–15:30 IST = 375 min / 5 = 75 bars), so the entire window
at session open is drawn from the prior day's data.

**Fix:** Group by `(contract_name, session_date)` instead — the session_date column already exists
on the chain (populated by `build_session_chain()`).

---

### 1.5 Key Code: Persistence Counter (`signal/zscores.py`, lines 18–34)

```python
def persistence(series: pd.Series) -> pd.Series:
    signs = np.sign(series.fillna(0))
    run = []
    current = 0
    prev = 0
    for sign in signs:
        if sign == 0:
            current = 0
        elif sign == prev:
            current += 1
        else:
            current = 1
        prev = sign
        run.append(current)
    return pd.Series(run, index=series.index)

out["same_sign_persistence"] = out.groupby("contract_name", group_keys=False)["zscore"].apply(persistence)
```

**Behavior trace on `[1, 1, -1, -1, -1, 0]`:**
```
sign: +1  → current=1,  prev=+1
sign: +1  → current=2,  prev=+1
sign: -1  → current=1,  prev=-1
sign: -1  → current=2,  prev=-1
sign: -1  → current=3,  prev=-1
sign:  0  → current=0,  prev= 0
result: [1, 2, 1, 2, 3, 0]
```

Counter starts at 1 on first bar of each run and increments ✓  
Counter resets to 0 on sign flip (to 1, not 0 — but the **first bar** of the new run gets 1) ✓  
NaN (filled to 0) resets to 0 ✓  

**Note:** The persistence counter is also applied via `groupby("contract_name")` only, same
session-boundary issue as z-scores. Must also be fixed to group by `(contract_name, session_date)`.

---

### 1.6 Configuration Parameters

```python
entry_z:             1.5          # |zscore| >= this to enter
exit_z:              0.5          # |zscore| <= this to exit
stop_z:              3.5          # |zscore| >= this → stop loss
persistence_bars:    2            # min consecutive same-sign bars
zscore_window_5m:    75           # rolling window at 5-min bars
zscore_window_1m:    375          # rolling window at 1-min bars
min_edge_to_cost_ratio: 1.5       # gross_edge_lot / estimated_cost >= this
```

---

### 1.7 Existing DataFrame Columns Available for Session Fix

The `chain` DataFrame already carries a `session_date` column (populated in
`preprocess/option_chain.py`, `build_session_chain()`). The fix requires no new data.

---

## 2. Direction & Edge Convention Verification

### 2.1 Butterfly Direction Convention (CME Group, Hull, Wikipedia)

Standard market convention:
- **Long butterfly** = BUY 1 wing-low + SELL 2 body + BUY 1 wing-high
  - Short body (ATM), long outer wings
  - Short vega: profits when body IV **falls** toward fair value
- **Short butterfly** = SELL 1 wing-low + BUY 2 body + SELL 1 wing-high
  - Long body (ATM), short outer wings  
  - Long vega: profits when body IV **rises** toward fair value

The `_build_actions` implementation matches this universal convention ✓

### 2.2 Vol-Arb Direction Mapping

| Body IV vs eSSVI Fair Value | Z-score sign | Correct direction | Code assignment |
|---|---|---|---|
| Overpriced (iv_market > iv_essvi) | z > 0 | LONG_BFLY (sell dear body) | `else: LONG_BFLY` ✓ |
| Underpriced (iv_market < iv_essvi) | z < 0 | SHORT_BFLY (buy cheap body) | `if z < 0: SHORT_BFLY` ✓ |

**Verdict: direction assignment is correct as written.** No fix needed.

### 2.3 Edge Formula Verification

For LONG_BFLY (body overpriced, z > threshold):
- We pay `market_premium` to enter (debit spread)
- Model fair value = `model_premium`; body overpriced → model_premium > market_premium
- Edge = `model_premium - market_premium` > 0 (we buy below fair value) ✓

Numerical example:
- Wings at market ≈ model price; body market_price = 90 vs model_price = 80
- market_premium = 100 - 2×90 + 100 = 20
- model_premium  = 100 - 2×80 + 100 = 40
- edge = 40 - 20 = 20 > 0 ✓

For SHORT_BFLY (body underpriced, z < -threshold):
- We receive `market_premium` to enter (credit spread)
- Body underpriced → body market_price < model_price → market_premium > model_premium
- Edge = `market_premium - model_premium` > 0 (we sell above fair value) ✓

Numerical example:
- Wings at market ≈ model price; body market_price = 70 vs model_price = 80
- market_premium = 100 - 2×70 + 100 = 60
- model_premium  = 100 - 2×80 + 100 = 40
- edge = 60 - 40 = 20 > 0 ✓

**Verdict: edge formulas are correct as written.** No fix needed.

---

## 3. Session-Boundary Fix: pandas Rolling Pattern

The canonical pattern for groupby-reset rolling in pandas uses `transform`:

```python
# Group by BOTH contract and session so rolling never crosses session boundaries
grouped = out.groupby(["contract_name", "session_date"], group_keys=False)["residual_iv"]
out["residual_mean_roll"] = grouped.transform(
    lambda s: s.rolling(window, min_periods=min_periods).mean()
)
```

Key properties:
- `groupby(...).transform(lambda s: s.rolling(...))` returns a Series with the same index as `out`,
  so direct column assignment works without index gymnastics.
- When `min_periods == window` (the default), the first `window-1` bars of each group are NaN.
- With the current setting `min_periods = min(20, window)`, early-session bars 1–19 are NaN;
  bars 20–74 have a partial-window estimate. This is an intentional config choice (warmup = 20 bars).

**min_periods recommendation:** Keep `min_periods = min(20, window)` as it allows signal to form
after 20 bars (100 minutes at 5-min) rather than waiting 75 bars (the full session). Early NaN
bars are naturally filtered by `same_sign_persistence < persistence_bars`.

---

## 4. Testing Setup

No existing test framework. Need to add pytest.

**Add to `pyproject.toml`:**
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Patterns to use:**
- `@pytest.mark.parametrize` for discrete signal states (positive/negative/zero z-score, each direction)
- Factory fixture (`make_session_panel`) in `conftest.py` for multi-session intraday panels
- `pd.isna()` / `.isna().all()` for NaN assertions (not `== float('nan')`)
- `pytest.approx(val, abs=1e-6)` for floating-point comparisons

Tests go in `tests/test_signal.py`. The 6 required test cases per the spec are all unit tests
(no I/O, no backtest engine) against the pure signal functions.

---

## 5. Summary of Required Changes

| Item | Status | Action |
|---|---|---|
| Direction: z < 0 → SHORT_BFLY | **Correct** | Add 3-line comment documenting verified correctness |
| Edge: LONG_BFLY = model - market | **Correct** | No change |
| Edge: SHORT_BFLY = market - model | **Correct** | No change |
| Z-score rolling window crosses sessions | **BUG** | Group by (contract_name, session_date) |
| Persistence counter crosses sessions | **BUG** | Same groupby fix |
| min_periods | Acceptable | Keep min(20, window); document rationale |
| Test framework | Missing | Add pytest; write tests/test_signal.py |
