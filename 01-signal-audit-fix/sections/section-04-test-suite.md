# Section 04 — Test Suite

## Overview

This section creates `tests/test_signal.py` — the complete pytest test suite for the signal pipeline. It depends on sections 01, 02, and 03 being complete:

- **Section 01** (`section-01-pytest-setup`) must be done first: `pyproject.toml` must have `pytest>=8.0` in dev dependencies and `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `pythonpath = ["src"]`, and the `tests/` directory must exist.
- **Section 02** (`section-02-zscores-fix`) must be done first: `src/essvi_bfly/signal/zscores.py` must use `groupby(["contract_name", "session_date"])` and have the `.reindex(out.index)` guard.
- **Section 03** (`section-03-candidate-comments`) must be done first, though it is comment-only and does not affect test behaviour.

---

## File to Create

**`tests/test_signal.py`** at the project root (same level as `src/` and `pyproject.toml`).

No `tests/__init__.py` should exist.

---

## Prerequisite: Move `persistence` to Module Scope

The `persistence` function must be importable directly from `essvi_bfly.signal.zscores` for `test_persistence_counter`. If it is currently defined as a nested function inside `add_residual_zscores`, move it to module scope (before `add_residual_zscores` in the file). The function body is **unchanged**. The call inside `add_residual_zscores` will still resolve correctly after the move.

After this move, tests can do:
```python
from essvi_bfly.signal.zscores import persistence, add_residual_zscores
```

This is a minor refactor within this section's scope — the behavior of `add_residual_zscores` is identical.

---

## Imports

```python
import types
import unittest.mock

import numpy as np
import pandas as pd
import pytest

from essvi_bfly.backtest.engine import BacktestEngine
from essvi_bfly.config import BacktestConfig
from essvi_bfly.signal.candidate_selection import select_candidates
from essvi_bfly.signal.zscores import add_residual_zscores, persistence
```

---

## `make_butterfly_chain` Helper

Define this as a plain function (not a pytest fixture) at the top of the test file. It returns a 3-tuple `(chain_df, diagnostics_df, config)`.

```python
def make_butterfly_chain(
    body_zscore: float,
    body_iv_market: float,
    body_iv_essvi: float,
    body_persistence: int = 3,
    lot_size: float = 1.0,
    contract_multiplier: float = 1.0,
) -> tuple:
```

### Chain DataFrame — 3 rows (wing_low, body, wing_high)

| Column | wing_low | body | wing_high | Notes |
|---|---|---|---|---|
| `contract_name` | "C_LOW" | "C_BODY" | "C_HIGH" | Distinct strings |
| `session_date` | "2024-01-01" | "2024-01-01" | "2024-01-01" | |
| `bar_close` | `pd.Timestamp("2024-01-01 10:00")` | same | same | |
| `root_symbol` | "NIFTY" | "NIFTY" | "NIFTY" | |
| `expiry_code` | "26JAN" | "26JAN" | "26JAN" | |
| `option_side` | "CE" | "CE" | "CE" | |
| `strike` | 17900.0 | 18000.0 | 18100.0 | Equidistant by 100 |
| `forward` | 18000.0 | 18000.0 | 18000.0 | |
| `tau_years` | 0.1 | 0.1 | 0.1 | |
| `mid` | 100.0 (approx) | 120.0 (approx) | 100.0 (approx) | Rough BS values; exact values don't affect direction tests |
| `quote_ok` | True | True | True | |
| `iv_market` | 0.20 | `body_iv_market` | 0.20 | Wings neutral |
| `iv_essvi` | 0.20 | `body_iv_essvi` | 0.20 | Wings neutral |
| `residual_iv` | 0.0 | `body_iv_market - body_iv_essvi` | 0.0 | |
| `zscore` | 0.0 | `body_zscore` | 0.0 | |
| `same_sign_persistence` | 0 | `body_persistence` | 0 | |
| `spread` | 0.01 | 0.01 | 0.01 | |
| `lot_size` | `lot_size` | `lot_size` | `lot_size` | |
| `contract_multiplier` | `contract_multiplier` | `contract_multiplier` | `contract_multiplier` | |

For `mid`, set approximate Black-Scholes prices. Use simple ATM-region values: wing low/high = 100.0 each, body = 120.0 (body is near ATM so slightly higher premium). The exact mid values affect the `market_premium` butterfly spread calculation, so ensure that `market_premium = low_mid - 2 * body_mid + high_mid` produces a reasonable non-negative value. With the example values: `100 - 2*120 + 100 = -40` (negative). Use `low=200, body=90, high=200` instead so `market_premium = 200 - 180 + 200 = 220`. Or simply ensure wings have higher mid than body for reasonable butterfly structure. The key requirement is that `market_premium > 0` to avoid edge computation issues.

**Simpler approach:** set `mid` consistently so `_structure_value(low, body, high, "mid")` > 0:
- wing_low mid = 150.0, body mid = 80.0, wing_high mid = 150.0
- market_premium = 150 - 160 + 150 = 140 > 0 ✓

### Diagnostics DataFrame — 1 row

| Column | Value |
|---|---|
| `bar_close` | `pd.Timestamp("2024-01-01 10:00")` |
| `root_symbol` | "NIFTY" |
| `expiry_code` | "26JAN" |
| `converged` | True |
| `rmse` | 0.001 |

### Config

Use `BacktestConfig` with these overrides from defaults:

```python
config = BacktestConfig(
    enforce_otm_structure_side=False,
    require_positive_edge=True,
    entry_z=1.5,
    persistence_bars_5m=2,
    bar_freq="5min",
    leg_brokerage_per_order=0.0,
    min_edge_to_cost_ratio=0.0,
    fee_rate=0.0,
    tax_rate=0.0,
)
```

Setting `leg_brokerage_per_order=0.0`, `min_edge_to_cost_ratio=0.0`, `fee_rate=0.0`, `tax_rate=0.0` ensures that even small synthetic edge values are not filtered out by transaction cost checks. The tests verify the sign and direction of edge, not absolute values.

---

## The 8 Tests

### 1. `test_build_actions_long_bfly_convention`

Guards the audit verdict: LONG_BFLY entry = BUY wing_low, SELL body, SELL body, BUY wing_high.

```python
def test_build_actions_long_bfly_convention():
    candidate = types.SimpleNamespace(
        direction="LONG_BFLY",
        wing_low_contract="C_LOW",
        body_contract="C_BODY",
        wing_high_contract="C_HIGH",
    )
    low = object()
    body = object()
    high = object()
    engine = unittest.mock.MagicMock(spec=BacktestEngine)
    actions = BacktestEngine._build_actions(engine, candidate, (low, body, high), is_exit=False)
    assert [(a, c) for a, c, _ in actions] == [
        ("BUY",  "C_LOW"),
        ("SELL", "C_BODY"),
        ("SELL", "C_BODY"),
        ("BUY",  "C_HIGH"),
    ]
```

### 2. `test_persistence_counter_sign_flip`

```python
def test_persistence_counter_sign_flip():
    series = pd.Series([1.2, 1.5, -1.3, -1.8, -2.0, float('nan')])
    result = persistence(series)
    assert list(result) == [1, 2, 1, 2, 3, 0]
```

### 3. `test_persistence_counter_leading_nan`

Validates the session-open pattern where z-scores are NaN during warmup.

```python
def test_persistence_counter_leading_nan():
    series = pd.Series([float('nan'), float('nan'), 1.5, 1.8, float('nan'), 2.0])
    result = persistence(series)
    assert list(result) == [0, 0, 1, 2, 0, 1]
```

### 4. `test_zscore_rolling_within_session`

The regression guard for the session-boundary fix. This test must fail against the old code and pass after section-02's fix is applied.

```python
def test_zscore_rolling_within_session():
    # Build 2-session panel: 30 bars per session for a single contract
    n_per_session = 30
    rng = np.random.default_rng(42)

    def make_session(date_str, start_time):
        times = pd.date_range(start_time, periods=n_per_session, freq="5min")
        return pd.DataFrame({
            "contract_name": "TEST_CONTRACT",
            "session_date": date_str,
            "bar_close": times,
            "residual_iv": np.linspace(0.01, 0.10, n_per_session),
            # Add all columns needed by add_residual_zscores (it only uses residual_iv,
            # contract_name, session_date, bar_close — all others can be omitted or set to 0)
        })

    s1 = make_session("2024-01-01", "2024-01-01 09:15")
    s2 = make_session("2024-01-02", "2024-01-02 09:15")
    chain = pd.concat([s1, s2], ignore_index=True)

    config = BacktestConfig(zscore_window_5m=10, bar_freq="5min")
    # min_periods = min(20, 10) = 10, so bars 0-9 are NaN, bar 9+ is finite

    result = add_residual_zscores(chain, config)

    sess1 = result[result["session_date"] == "2024-01-01"].sort_values("bar_close").reset_index(drop=True)
    sess2 = result[result["session_date"] == "2024-01-02"].sort_values("bar_close").reset_index(drop=True)

    # Session 1: first 9 bars NaN (indices 0-8), bar 9+ finite
    assert sess1.loc[:8, "zscore"].isna().all(), "Session 1 bars 0-8 should be NaN"
    assert sess1.loc[9:, "zscore"].notna().all(), "Session 1 bar 9+ should be finite"

    # Session 2: first 9 bars NaN — KEY REGRESSION GUARD (fails before fix)
    assert sess2.loc[:8, "zscore"].isna().all(), "Session 2 bars 0-8 should be NaN (session boundary must reset)"
    assert sess2.loc[9:, "zscore"].notna().all(), "Session 2 bar 9+ should be finite"

    # Persistence counter has no NaN (verifies .reindex guard)
    assert result["same_sign_persistence"].isna().sum() == 0, "same_sign_persistence must have no NaN"
```

**Note on `add_residual_zscores` column requirements:** Read the actual function to see what columns it accesses beyond `residual_iv`, `contract_name`, `session_date`, and `bar_close`. If it accesses other columns (e.g., `bar_close` for sorting only), the synthetic DataFrame may need those too. Add any missing columns as needed with placeholder values.

### 5. `test_direction_long_bfly`

```python
def test_direction_long_bfly():
    # body iv_market > iv_essvi → body overpriced → LONG_BFLY
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=+2.0,
        body_iv_market=0.25,
        body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    assert len(candidates) >= 1
    directions = [c.direction for c in candidates]
    assert "LONG_BFLY" in directions
```

### 6. `test_direction_short_bfly`

```python
def test_direction_short_bfly():
    # body iv_market < iv_essvi → body underpriced → SHORT_BFLY
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=-2.0,
        body_iv_market=0.15,
        body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    assert len(candidates) >= 1
    directions = [c.direction for c in candidates]
    assert "SHORT_BFLY" in directions
```

### 7. `test_edge_long_bfly_positive`

```python
def test_edge_long_bfly_positive():
    # body overpriced → model_premium > market_premium → edge = model - market > 0
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=+2.0,
        body_iv_market=0.25,
        body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    long_candidates = [c for c in candidates if c.direction == "LONG_BFLY"]
    assert len(long_candidates) >= 1
    assert all(c.theoretical_edge > 0 for c in long_candidates)
```

### 8. `test_edge_short_bfly_positive`

```python
def test_edge_short_bfly_positive():
    # body underpriced → market_premium > model_premium → edge = market - model > 0
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=-2.0,
        body_iv_market=0.15,
        body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    short_candidates = [c for c in candidates if c.direction == "SHORT_BFLY"]
    assert len(short_candidates) >= 1
    assert all(c.theoretical_edge > 0 for c in short_candidates)
```

---

## Passing All `select_candidates` Filters

The `select_candidates` function has several filters a synthetic candidate must satisfy. The `make_butterfly_chain` helper must ensure:

1. `(bar_close, root_symbol, expiry_code) in ok_keys` — the diagnostics row must match.
2. `quote_ok = True` for all three legs.
3. `same_sign_persistence >= config.persistence_bars_5m` — body must have `persistence >= 2`.
4. `abs(zscore) >= config.entry_z` — must be ≥ 1.5 (use ±2.0 so 2.0 > 1.5 ✓).
5. `(body_strike − low_strike) == (high_strike − body_strike)` — equidistant by 100 ✓.
6. `enforce_otm_structure_side=False` — skips the forward/strike OTM check.
7. `np.isfinite(iv_essvi)` — all three legs must have finite `iv_essvi` (0.20 ✓).
8. `require_positive_edge=True` — the edge must be > 0. With `iv_market=0.25` vs `iv_essvi=0.20` (body), the butterfly prices should produce a non-zero edge.
9. `gross_edge_lot > estimated_cost` — set all cost-related config to zero to make this trivially pass.

If any test returns 0 candidates, add a print of why the filter is rejecting — check which filter condition fails.

---

## Running All Tests

```bash
cd /Volumes/One Touch/NSE/onesec/curvex
uv run pytest tests/test_signal.py -v
```

All 8 tests must pass. If `test_zscore_rolling_within_session` fails, section-02 may not have been applied yet.

---

## File Path Summary

- **Create:** `tests/test_signal.py`
- **Modify (minor refactor for testability):** `src/essvi_bfly/signal/zscores.py` — move `persistence` to module scope (if currently nested)
- **Do NOT create:** `tests/__init__.py`

---

## Implementation Notes (actual vs planned)

**`select_candidates` returns `pd.DataFrame`:** Plan tests used `[c.direction for c in candidates]` which iterates column names on a DataFrame. Implemented as `candidates["direction"].tolist()` and boolean indexing `candidates[candidates["direction"] == "LONG_BFLY"]`.

**Direction assertions strengthened:** Changed from `"LONG_BFLY" in list` to `(candidates["direction"] == "LONG_BFLY").all()` — stronger assertion that locks sign convention completely.

**BS-consistent mid prices in `make_butterfly_chain`:** Plan's suggested static mid values (wing=150, body=80) produce `market_premium=140` vs `model_premium≈3`, giving negative edge and zero candidates. Used `price_option_forward(forward, strike, tau, rate, body_iv_market, option_side)` to compute mid prices, ensuring `edge = 2*(body_BS(iv_market) - body_BS(iv_essvi)) ≈ 228` for LONG_BFLY and ≈222 for SHORT_BFLY.

**NaN warmup clarification:** With `window=10, min_periods=10`: bars at indices 0–8 (9 bars) are NaN; bar 9+ is finite. The `rolling` window at index 9 has exactly 10 values, satisfying `min_periods=10`. The spec comment "bars 0-9 are NaN" is incorrect — bar 9 is finite.
