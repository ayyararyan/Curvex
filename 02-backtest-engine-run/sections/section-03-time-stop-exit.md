# Section 03: Time-Stop Exit

## Overview

Replace the "discard-on-no-fill" exit behavior in `_simulate_exit` with a two-phase time-stop that guarantees every entered trade produces an exit record. Add `_fill_leg_with_fallback` for forced fills at the time-stop bar.

**Depends on:** section-01 (ButterflyTrade fields + logging), section-02 (engine audit, orders=4 fix)  
**Blocks:** section-04, section-07

---

## Background: The Problem

`_simulate_exit` currently iterates `max_holding_bars` rows looking for a bar where a trigger fires (|z| ≤ exit_z or |z| ≥ stop_z) AND all 4 legs fill. If no such bar exists, it returns `(None×5)` and the trade is discarded. This drops physically real trades that simply held without a clean fill bar — non-physical for liquid NSE index options.

---

## Return Tuple Change

Old: `(exit_bar, exit_z, exit_cashflow, exit_turnover, fills) | (None×5)`  
New: `(exit_bar, exit_z, exit_cashflow, exit_turnover, fills, exit_type, fill_quality) | None`

`None` is returned **only** when the body contract has zero bars after entry (genuine data absence). Every other entered trade must produce a tuple.

`exit_type` values: `'profit_take'` | `'stop_loss'` | `'time_stop'` | `'time_stop_no_quote'`  
`fill_quality` values: `None` (normal) | `'degraded'` (stale lp used)

---

## Tests First

Add to `tests/test_engine.py` (append to file created in section-02).

### `_fill_leg_with_fallback` tests

```python
# test_fill_leg_with_fallback_buy_uses_sp1_when_valid
# When sp1 > 0 and non-NaN, BUY fill uses sp1, filled=True

# test_fill_leg_with_fallback_sell_uses_bp1_when_valid
# When bp1 > 0 and non-NaN, SELL fill uses bp1, filled=True

# test_fill_leg_with_fallback_buy_falls_back_to_lp_when_sp1_nan
# When sp1 is NaN, BUY uses lp × (1 + half_spread). filled=True
# half_spread = config.max_spread_pct / 4 = 0.12/4 = 0.03
# lp=100 → expected price = 103.0

# test_fill_leg_with_fallback_sell_falls_back_to_lp_when_bp1_nan
# When bp1 is NaN, SELL uses lp × (1 - half_spread). lp=100 → expected = 97.0

# test_fill_leg_with_fallback_returns_not_filled_when_both_nan
# When sp1 (or bp1) AND lp are all NaN/zero → filled=False
```

### `_simulate_exit` tests

```python
# test_simulate_exit_profit_take_exit_type
# |z| <= exit_z fires on bar 2 → exit_type='profit_take'

# test_simulate_exit_stop_loss_exit_type
# |z| >= stop_z fires on bar 2 → exit_type='stop_loss'

# test_simulate_exit_stop_loss_wins_over_profit_take_at_same_bar
# When both conditions true simultaneously, exit_type='stop_loss'
# (use custom config with exit_z=4.0, stop_z=0.1 to force simultaneous triggers)

# test_simulate_exit_time_stop_when_no_trigger_fires
# No bar has |z| <= exit_z or |z| >= stop_z within max_holding_bars
# → exit at last bar, exit_type='time_stop'

# test_simulate_exit_returns_7_tuple_not_5
# Unpacking to 7 elements succeeds without ValueError

# test_simulate_exit_returns_none_when_body_has_no_bars_after_entry
# Returns None when body contract has zero rows after entry_bar

# test_simulate_exit_staleness_guard_sets_degraded_fill_quality
# When lp is used as fallback AND trade_age_seconds > max_trade_age_seconds × 2
# → fill_quality == 'degraded'
# Setup: sp1=NaN, bp1=NaN, trade_age_seconds=config.max_trade_age_seconds * 3

# test_simulate_exit_time_stop_walks_back_when_wing_missing_at_last_bar
# Wing contract missing at max_holding_bars bar but present at bar-1
# → uses bar-1 quotes, does not return None

# test_simulate_exit_time_stop_no_quote_when_no_walkback_succeeds
# Wing missing for all 3 walkback bars → exit_type='time_stop_no_quote', non-None tuple
```

---

## Implementation

### File: `src/essvi_bfly/backtest/engine.py`

#### 1. Add `_fill_leg_with_fallback`

Add as a method of `BacktestEngine` before `_simulate_exit`:

```python
def _fill_leg_with_fallback(self, quote_row: pd.Series, action: str) -> FillResult:
    """Fill using best quote; fall back to lp with synthetic spread adjustment.

    For BUY: try sp1 first; if zero/NaN, use lp × (1 + half_spread_estimate).
    For SELL: try bp1 first; if zero/NaN, use lp × (1 - half_spread_estimate).
    half_spread_estimate = config.max_spread_pct / 4.
    If lp is also zero/NaN: filled=False.
    """
```

Logic:
- `half_spread = self.config.max_spread_pct / 4`
- BUY: read `sp1`. If `pd.notna(sp1) and sp1 > 0` → `FillResult(float(sp1), True, "ask_fill")`. Else: read `lp`. If `pd.notna(lp) and lp > 0` → `FillResult(float(lp) * (1 + half_spread), True, "lp_fallback")`. Else: `FillResult(None, False, "no_quote")`.
- SELL: mirror with `bp1` and `lp × (1 - half_spread)`.

#### 2. Rewrite `_simulate_exit` (Two-Phase)

```python
def _simulate_exit(
    self,
    chain: pd.DataFrame,
    chain_index: pd.DataFrame,
    candidate,
    entry_bar: pd.Timestamp,
    lot_size: float,
    contract_multiplier: float,
) -> tuple[pd.Timestamp, float, float, float, list[FillResult], str, str | None] | None:
    """Simulate exit. Returns 7-tuple or None (only on zero body bars after entry)."""
```

**Phase 1 — Primary exit loop:**

```python
contract_rows = chain[chain["contract_name"] == candidate.body_contract].sort_values("bar_close")
later = contract_rows[contract_rows["bar_close"] > entry_bar].head(self.config.max_holding_bars)
if later.empty:
    return None

for row in later.itertuples(index=False):
    z = getattr(row, "zscore", np.nan)
    is_stop_loss = abs(z) >= self.config.stop_z
    is_profit_take = abs(z) <= self.config.exit_z
    if is_stop_loss or is_profit_take:
        exit_type = "stop_loss" if is_stop_loss else "profit_take"
        leg_quotes = self._get_leg_open_quotes(chain_index, row.bar_close, candidate)
        if leg_quotes is None:
            continue
        exit_actions = self._build_actions(candidate, leg_quotes, is_exit=True)
        fills = [fill_leg(q, action) for action, _, q in exit_actions]
        if all(fill.filled for fill in fills):
            cf = self._cashflow_from_fills(exit_actions, fills, lot_size, contract_multiplier)
            tv = self._turnover_from_fills(fills, lot_size, contract_multiplier)
            return row.bar_close, z, cf, tv, fills, exit_type, None
```

Stop-loss checked before profit-take so it wins at ties.

**Phase 2 — Time-stop fallback:**

Walk back up to 3 bars from the tail of `later` looking for a bar where all 3 contracts have rows:

```python
tail_rows = list(later.itertuples(index=False))[-3:]
time_stop_bar = None
time_stop_quotes = None
time_stop_z = np.nan
for ts_row in reversed(tail_rows):
    quotes = self._get_leg_open_quotes(chain_index, ts_row.bar_close, candidate)
    if quotes is not None:
        time_stop_bar = ts_row.bar_close
        time_stop_z = getattr(ts_row, "zscore", np.nan)
        time_stop_quotes = quotes
        break
```

If `time_stop_quotes` found: fill all 4 legs using `_fill_leg_with_fallback`. Check staleness: if any leg's `trade_age_seconds > self.config.max_trade_age_seconds * 2`, set `fill_quality = "degraded"`. Set `exit_type = "time_stop"`.

If not found (no walkback succeeded): set `exit_type = "time_stop_no_quote"`. Use last bar's `bar_close` and `zscore`. All fills are `FillResult(None, False, "no_quote")`. Set `fill_quality = None`.

Cashflow for partial fills: use `(fill.price or 0.0)` in cashflow sum.

Return the 7-tuple.

#### 3. Update `_simulate` Call Site

Change from:
```python
exit_bar, exit_z, exit_cashflow, exit_turnover, exit_fill_results = self._simulate_exit(...)
if exit_bar is None or exit_fill_results is None:
    continue
```

To:
```python
exit_result = self._simulate_exit(
    chain, chain_index, candidate, entry_bar, lot_size, contract_multiplier
)
if exit_result is None:
    continue
exit_bar, exit_z, exit_cashflow, exit_turnover, exit_fill_results, exit_type, fill_quality = exit_result
```

#### 4. Populate `exit_type` and `exit_fill_quality` in `ButterflyTrade`

When constructing the `ButterflyTrade` in `_simulate`:
```python
trade = ButterflyTrade(
    ...
    status="CLOSED",
    exit_type=exit_type,
    exit_fill_quality=fill_quality,
)
```

#### 5. Fix Exit Fills Recording for Time-Stop

The current code re-calls `_get_leg_open_quotes` when building exit fills rows — this crashes for `time_stop_no_quote` exits where `chain_index` has no entry at that bar. Fix by reconstructing actions from the candidate directly:

```python
exit_leg_specs = [
    ("SELL" if candidate.direction == "LONG_BFLY" else "BUY", candidate.wing_low_contract),
    ("BUY" if candidate.direction == "LONG_BFLY" else "SELL", candidate.body_contract),
    ("BUY" if candidate.direction == "LONG_BFLY" else "SELL", candidate.body_contract),
    ("SELL" if candidate.direction == "LONG_BFLY" else "BUY", candidate.wing_high_contract),
]
for (action, contract_name), fill in zip(exit_leg_specs, exit_fill_results):
    fills_rows.append({
        "trade_id": trade_id,
        "bar_close": exit_bar,
        "contract_name": contract_name,
        "action": action,
        "fill_price": fill.price,
        "reason": f"exit_{fill.reason}",
    })
```

---

## Config Fields Used

| Field | Default | Purpose |
|---|---|---|
| `exit_z` | 0.5 | Profit-take trigger |
| `stop_z` | 3.5 | Stop-loss trigger |
| `max_holding_bars` | 8 (5min) | Phase 1 limit; time-stop at this bar |
| `max_spread_pct` | 0.12 | `half_spread = max_spread_pct / 4 = 0.03` |
| `max_trade_age_seconds` | 300 | Staleness guard: degrade if `> 600` |

---

## Files Modified

| File | Change |
|---|---|
| `src/essvi_bfly/backtest/engine.py` | Add `_fill_leg_with_fallback`; rewrite `_simulate_exit`; update `_simulate` call site; fix exit fills recording |
| `tests/test_engine.py` | Append time-stop tests |

`structures.py` is **not modified** here — section-01 handles that.

## Implementation Status: COMPLETE

**Tests:** 37/37 pass (16 new tests added for this section).

**Deviations from plan:**
- `time_stop_no_quote` path sets `fill_quality='no_quote'` (plan said `None`). Allows downstream filtering.
- `_cashflow_from_fills` uses `fill.price if fill.price is not None else 0.0` not `fill.price or 0.0` (avoids treating zero premium as None).
- 2 extra tests added beyond plan: phase-1 fallthrough (trigger fires but quotes missing) and SHORT_BFLY exit.
