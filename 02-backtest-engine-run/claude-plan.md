# Implementation Plan — Split 02: Backtest Engine & End-to-End Run

---

## Background and Goal

This plan covers the audit and repair of the eSSVI butterfly backtest engine (`src/essvi_bfly/backtest/engine.py`) and the production of honest raw output CSVs from a full January 2026 run on NIFTY and BANKNIFTY.

**Pre-condition:** Split 01 (signal module corrections — direction logic, edge sign, rolling z-score boundary) is already merged. This plan assumes a correct signal pipeline and focuses exclusively on the execution layer and data pipeline.

The engine takes a stream of `ButterflyCandidate` signals (with direction, body/wing contracts, and z-score) and simulates leg fills, entry/exit cashflows, transaction costs, and per-trade P&L. The fixes and additions required are:

1. Confirm `_build_actions` action sequences are correct (already correct in code — verify only)
2. Fix `_cashflow_from_fills` transaction-cost bug (`orders=1` → `orders=4`)
3. Replace the "discard-on-no-fill" exit behavior with a time-stop that forces an exit at `max_holding_bars`
4. Add `exit_type` and `exit_fill_quality` to `ButterflyTrade` and the output trades DataFrame
5. Add `cumulative_pnl` to the nav output
6. Wrap the session loop with data-error resilience (skip missing/corrupt sessions; raise on logic errors)
7. Add a lightweight smoke-test script for the data pipeline
8. Run the full backtest end-to-end and verify outputs

---

## Section 1: Verify `_build_actions`

### What This Does

`_build_actions(candidate, leg_quotes, is_exit)` in `engine.py` returns a list of 4 tuples `(action, contract_name, quote_row)` representing the four legs of a butterfly trade. The list is consumed by `fill_leg` and `_cashflow_from_fills`.

### Required Behavior

The correct 1-2-1 structure for all four (direction × phase) combinations:

| Direction | Phase | Wing Low | Body | Body | Wing High |
|---|---|---|---|---|---|
| LONG_BFLY | entry | BUY | SELL | SELL | BUY |
| LONG_BFLY | exit | SELL | BUY | BUY | SELL |
| SHORT_BFLY | entry | SELL | BUY | BUY | SELL |
| SHORT_BFLY | exit | BUY | SELL | SELL | BUY |

The body contract always appears **twice** — two independent `fill_leg` calls on the same quote row. The 2× body fill naturally accumulates `2 × body_price` in the cashflow sum.

**Known limitation:** `fill_leg` checks `bq1 > 0` but not `bq1 >= 2`. For 1-lot sizing across each leg individually this is acceptable; document in commit message.

### Audit Instruction

Read the current implementation of `_build_actions` in `engine.py`. Compare against the table above. **The as-coded sequences in the current code are expected to already be correct** — the only action needed is verification. If any cell differs, fix it. Record the audit outcome (confirmed-correct / fixed-N-cells) in the git commit message.

### Function Signature (unchanged)

```python
def _build_actions(
    self,
    candidate: ButterflyCandidate,
    leg_quotes: tuple[pd.Series, pd.Series, pd.Series],
    is_exit: bool,
) -> list[tuple[str, str, pd.Series]]:
    """Return ordered list of (action, contract_name, quote_row) for 4 legs.

    Order: wing_low, body, body, wing_high.
    LONG_BFLY entry: BUY, SELL, SELL, BUY.
    LONG_BFLY exit:  SELL, BUY, BUY, SELL.
    SHORT_BFLY is the exact flip of LONG_BFLY.
    """
```

---

## Section 2: Fix `_cashflow_from_fills` and Transaction Costs

### Cashflow Formula (Correct, Do Not Change)

```python
(fill.price if action == "SELL" else -fill.price) * scale
```

SELL = positive (inflow), BUY = negative (outflow), `scale = lot_size × contract_multiplier`. This is the standard cash-ledger convention.

### Sign Verification

For a LONG_BFLY entry (body overpriced → sell body, buy wings):
- The two SELL body actions produce `+2 × body_price × scale`
- The two BUY wing actions produce `−wing_low_price × scale − wing_high_price × scale`
- Net `entry_cashflow` = `+2×body − wing_low − wing_high` (multiplied by scale)

In a correctly identified LONG_BFLY signal, the body is overpriced relative to the wings, so `2×body_mid > wing_low_mid + wing_high_mid`. But fills use **bid for SELL and ask for BUY** — with realistic spreads, the net entry_cashflow can be either sign. What matters is:

```
pnl = entry_cashflow + exit_cashflow − total_transaction_cost
```

For a profitable LONG_BFLY trade, the z-score reverts: the body cheapens and wings reprice, so `exit_cashflow` (selling wings back, buying body back) nets a positive residual. The sum `entry_cashflow + exit_cashflow` should be positive for any profitable trade.

**Sanity check (post-run):** For any profitable LONG_BFLY trade, `entry_cashflow + exit_cashflow > 0`. For a stopped-out trade, `entry_cashflow + exit_cashflow < total_transaction_cost`. This check belongs in the spot-check step.

### Transaction Cost — `orders=1` is Correct

`estimate_transaction_cost` is called with `orders=1` at both entry and exit. This is **correct** for NSE multi-leg strategy execution: all 4 butterfly legs are placed as a single combined order (via basket/strategy order), not 4 separate orders. Brokerage is ₹20 per combined butterfly order → ₹20 at entry + ₹20 at exit = ₹40 round-trip. Do not change `orders=1`.

The Opus review incorrectly flagged this as a bug — it applied US single-leg logic to NSE combined-order execution.

**Turnover note:** `_turnover_from_fills` correctly sums absolute fill prices across all 4 fills (body counted twice). For NSE STT/exchange fees computed on gross transaction value, this is the right denominator.

### Function Signatures (unchanged)

```python
def _cashflow_from_fills(
    self,
    actions: list[tuple[str, str, pd.Series]],
    fills: list[FillResult],
    lot_size: float,
    contract_multiplier: float,
) -> float:
    """Compute signed cashflow. SELL → positive. BUY → negative. Scaled by lot×multiplier."""

def _turnover_from_fills(
    self,
    fills: list[FillResult],
    lot_size: float,
    contract_multiplier: float,
) -> float:
    """Sum of absolute fill prices × lot × multiplier (gross transaction value)."""
```

---

## Section 3: Replace Exit "Discard" with Time-Stop

### Current Problem

`_simulate_exit` iterates up to `max_holding_bars` rows looking for a bar where an exit trigger fires (|z| ≤ exit_z or |z| ≥ stop_z) AND all 4 legs fill. If no such bar is found, the function returns `None` and the trade is discarded. For liquid NSE index options, this discards trades that simply held without a clean fill bar — an overly conservative and non-physical outcome.

### Desired Behavior

Two-phase exit:

**Phase 1 — Primary exit loop (same trigger logic as today):**
Iterate bars of the body contract from `entry_bar + 1` through `entry_bar + max_holding_bars`. For each bar, check:
- `abs(zscore) <= exit_z` (profit-take trigger), or
- `abs(zscore) >= stop_z` (stop-loss trigger)

Classify exit type at each candidate bar. If both triggers apply simultaneously at the same bar, **stop-loss takes priority** (risk management semantics: the move was large, cap the loss).

For each candidate exit bar, attempt `_get_leg_open_quotes` + `fill_leg` fills. If all 4 legs fill, return immediately with the exit type.

**Phase 2 — Time-stop fallback (new):**
If Phase 1 completes without any successful fill, use the last bar (`entry_bar + max_holding_bars`) as a forced exit. Fill each leg using:

```python
def _fill_leg_with_fallback(self, quote_row: pd.Series, action: str) -> FillResult:
    """Fill using best quote; fall back to lp with synthetic spread adjustment.

    For BUY: try sp1 first; if zero/NaN, use lp × (1 + half_spread_estimate).
    For SELL: try bp1 first; if zero/NaN, use lp × (1 - half_spread_estimate).
    half_spread_estimate = config.max_spread_pct / 4  (conservative proxy).
    If lp is also zero/NaN: fill price = NaN, filled = False.
    Returns FillResult(price, filled, reason).
    """
```

The synthetic spread adjustment prevents time-stop trades from appearing spuriously profitable (using raw `lp` ignores the bid-ask cross).

**Staleness guard:** Before using `lp` as fallback, check `trade_age_seconds` on the quote row. If `trade_age_seconds > config.max_trade_age_seconds * 2`, set `exit_fill_quality = "degraded"` in the trade record (even if fill succeeds). This flags trades where the last-traded price is stale.

**Missing wing row at time-stop:** If `_get_leg_open_quotes` returns `None` at the time-stop bar (a wing contract has no row in `chain_index` at that bar), walk back up to 3 bars looking for the most recent bar where all 3 contracts have rows. Use that bar's quotes for the time-stop fill. If still not found, mark `exit_type = "time_stop_no_quote"` and record `fill_price = NaN` for missing legs. **Do not return `None`** — every entered trade must have an exit record.

`_simulate_exit` should return `None` only if the body contract has **no bars at all** after the entry bar (genuine data absence, not a fill failure).

### Updated Dataclass Fields

Add to `ButterflyTrade` in `portfolio/structures.py`:

```python
exit_type: str | None = None
# Values: 'profit_take' | 'stop_loss' | 'time_stop' | 'time_stop_no_quote'

exit_fill_quality: str | None = None
# Values: None (normal) | 'degraded' (stale lp used)
```

### Updated Function Signature

```python
def _simulate_exit(
    self,
    chain: pd.DataFrame,
    chain_index: pd.MultiIndex,
    candidate: ButterflyCandidate,
    entry_bar: pd.Timestamp,
    lot_size: float,
    contract_multiplier: float,
) -> tuple[pd.Timestamp, float, float, float, list[FillResult], str, str | None] | None:
    """Simulate exit for one entered trade.

    Returns (exit_bar, exit_z, exit_cashflow, exit_turnover, fills, exit_type, fill_quality).
    exit_type: 'profit_take' | 'stop_loss' | 'time_stop' | 'time_stop_no_quote'.
    fill_quality: None | 'degraded'.
    Returns None only when the body contract has zero bars after entry (data absence).
    """
```

All call sites in `_simulate` that unpack the return tuple must be updated to receive the two new fields.

---

## Section 4: Nav Output — Add `cumulative_pnl`

The `_simulate` method builds `nav_rows` with per-trade `pnl`. The `butterfly_nav.csv` schema requires `cumulative_pnl`. This column is currently absent, causing a column-mismatch failure on first run.

Add `cumulative_pnl` computation before writing:

```python
def _build_nav(self, nav_rows: list[dict]) -> pd.DataFrame:
    """Convert per-trade pnl list to nav DataFrame with cumulative_pnl column.

    Sorts by trade_id. cumulative_pnl = cumsum of pnl across all trades.
    """
```

Alternatively, add it in `write_results` or at the point where the `nav` DataFrame is constructed. The column must be present in the output CSV.

---

## Section 5: Session-Level Error Handling

### Principle

Only data-loading errors may be caught and skipped. Logic errors must raise immediately.

**Data errors (safe to skip):**
- `FileNotFoundError` — parquet file missing from external drive
- `pyarrow.lib.ArrowInvalidError`, `pyarrow.lib.ArrowIOError` — corrupt/unreadable parquet
- `OSError` — transient OS/USB read failure (data lives on `/Volumes/One Touch/` external drive)
- `pandas.errors.EmptyDataError`, `pandas.errors.ParserError` — empty or malformed data

**Logic errors (must raise):**
- `KeyError` on a column that should exist post-calibration
- `ValueError` or `ZeroDivisionError` in cashflow math
- Any error inside `_simulate`, `_build_actions`, `_cashflow_from_fills`

### Implementation

In `BacktestEngine.run()`, wrap **only the data-loading call** for each `(symbol, session_date)`:

```python
try:
    artifacts = build_session_chain(manifest_session, session_date, symbol, config)
except (FileNotFoundError, ArrowInvalidError, ArrowIOError, OSError,
        pd.errors.EmptyDataError, pd.errors.ParserError) as e:
    logger.warning("Skipping %s %s — data load failed: %s", symbol, session_date, e)
    continue

if artifacts.option_bars.empty:
    logger.warning("Skipping %s %s — empty option chain", symbol, session_date)
    continue
```

**Calibration failures:** `calibrate_surface` internally handles per-slice errors by setting `converged=False` in diagnostics. If it raises at the session level (e.g., all slices fail simultaneously), treat this as a data error and skip the session. Add to the catch block: `except scipy.optimize.OptimizeWarning as e: ...` if it raises rather than warns.

**End-of-run checks:**
- If zero chain rows were produced across all sessions for a single root symbol, raise `RuntimeError` with a summary (not a silent empty CSV for that symbol).
- If zero chain rows across all symbols, raise `RuntimeError` with session skip log.

### Logging Setup

`engine.py` currently has no module-level logger. Add:

```python
import logging
logger = logging.getLogger(__name__)
```

In `__main__.py`, add a stderr handler so warnings surface during the run:

```python
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
```

---

## Section 6: Smoke-Test Script

### Purpose

`scripts/smoke_test_pipeline.py` verifies the data pipeline for a single session before committing to a full 21-session run. Exits with code 0 on pass, code 1 on any failure.

### Checks

For session `"2026_01_02"`, symbol `"NIFTY"` (overridable via `--session` / `--symbol` flags):

1. **Chain non-empty:** `chain` has at least 1 row.
2. **Tau positivity:** `tau_years > 0` for every row (no expired / negative tau).
3. **ATM mid prices:** For rows where `|ln(strike/forward)| <= 0.03` (ATM ±3%), `mid > 0`.
4. **Forward quality:** `forward` is non-null and within 1% of the underlying spot price at the same `bar_close` timestamp.
5. **Quote coverage:** `quote_ok == True` for at least 50% of rows.
6. **Calibration convergence:** At least 3 slices have `converged == True` in diagnostics.
7. **Bar count:** At least 60 bars per option contract (catches truncated parquet files).
8. **Strike coverage:** At least 5 distinct strikes within ATM ±5% per expiry.
9. **No duplicate index keys:** No duplicate `(bar_close, contract_name)` pairs (duplicates break `chain_index.loc[key]`).
10. **Underlying contract resolved:** The underlying contract from `config.underlying_spot_map["NIFTY"]` exists in the manifest and has non-empty data for this session.
11. **Session-boundary z-score regression guard:** First `zscore_window_5m` (75) bars should have `zscore == NaN`. Catches a regression of the Split 01 fix.

### Structure

```python
def check(label: str, condition: bool, detail: str = "") -> bool:
    """Print PASS/FAIL line with metric detail. Returns True if passed."""

def main() -> None:
    """Run smoke checks. Exit 0=pass, 1=any failure."""
```

Each check prints independently. All checks run even if early ones fail. Exit code is 1 if any check fails.

---

## Section 7: Performance — Per-Contract Bar Index

The current `_next_bar_for_contract` (engine.py) filters and sorts the full chain DataFrame on every call. With potentially thousands of candidates, this is O(candidates × rows) — likely the main bottleneck.

Before the candidate loop in `_simulate`, build a one-time index:

```python
def _build_contract_bar_index(self, chain: pd.DataFrame) -> dict[str, np.ndarray]:
    """Pre-compute sorted bar_close arrays per contract_name.

    Returns dict mapping contract_name → sorted array of bar_close timestamps.
    Used by _next_bar_for_contract for O(log N) bar lookup.
    """
```

`_next_bar_for_contract` then does a binary search (`np.searchsorted`) on the pre-built array instead of filtering the chain.

---

## Section 8: Unit Tests

Add to `tests/test_signal.py` (or a new `tests/test_engine.py`):

### Test `_build_actions` exhaustively

Four tests — one for each (direction × is_exit) combination. Each test:
- Creates a minimal `ButterflyCandidate` with known contract names
- Creates placeholder quote rows
- Calls `_build_actions`
- Asserts the 4 `(action, contract)` pairs match the required table exactly

### Test `_cashflow_from_fills` with a hand-computed example

One LONG_BFLY entry scenario with known prices:
- wing_low fill = 50 (BUY)
- body fill 1 = 80 (SELL)
- body fill 2 = 80 (SELL)
- wing_high fill = 50 (BUY)
- `scale = lot_size × multiplier = 1.0`

Expected cashflow: `−50 + 80 + 80 − 50 = +60`

Assert computed value equals 60.0 exactly. This pin-tests the sign convention against a known result.

---

## Section 9: Full Run and Output Verification

### Configuration

```
bar_freq = "5min"
root_symbols = ("NIFTY", "BANKNIFTY")
start_date = None, end_date = None  (all January 2026)
max_expiries_per_session = 1
entry_z = 1.5, exit_z = 0.5, stop_z = 3.5
persistence_bars_5m = 2
holding_bars_5m = 8
calibration_rmse_limit = 0.02
leg_brokerage_per_order = 20.0
fee_rate = 0.0005, tax_rate = 0.0005
```

### Run Command

```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run python scripts/run_backtest.py \
  --strategy butterfly \
  --bar-freq 5min \
  --root-symbol NIFTY \
  --root-symbol BANKNIFTY
```

**Output overwrite policy:** The run overwrites existing files in `outputs/essvi_bfly/reports/`. Before the first clean run, back up any prior outputs manually if needed. A `--run-tag` subdirectory option can be added in split 03 if versioning is needed.

### Expected Output CSVs

| File | Key columns |
|---|---|
| `butterfly_chain.csv` | bar_close, contract_name, iv_essvi, residual_iv, zscore, quote_ok |
| `butterfly_calibration_diagnostics.csv` | bar_close, root_symbol, expiry_code, rmse, converged |
| `butterfly_candidates.csv` | bar_close, direction, body_contract, theoretical_edge, estimated_cost |
| `butterfly_fills.csv` | trade_id, leg_index, action, contract_name, fill_price, fill_reason |
| `butterfly_trades.csv` | trade_id, entry_bar, exit_bar, direction, entry_zscore, exit_zscore, pnl, exit_type, exit_fill_quality |
| `butterfly_nav.csv` | trade_id, pnl, cumulative_pnl |

### Post-Run Spot Check

**Before spot-checking,** print calibration summary: per-symbol convergence rate and RMSE distribution. If convergence is < 50% for a symbol, the candidate pool is likely too thin for meaningful spot-check conclusions.

Sample 5 trades from `butterfly_trades.csv` and verify all of:

1. `entry_bar < exit_bar` — chronological integrity
2. `|entry_zscore| >= 1.5` — entry threshold respected
3. Profitable trades: `entry_cashflow + exit_cashflow > 0` (before costs)
4. Stopped trades: `exit_type == "stop_loss"` and `|exit_zscore| >= 3.5`
5. `lot_size × contract_multiplier` from the manifest matches the scaling in the trade (check via manifest lookup on `body_contract`)
6. LONG_BFLY trades: `entry_cashflow` sign direction is consistent with selling the body (positive contributions from the two body SELL fills exceed the wing BUY costs when body is truly expensive)

If any check fails, diagnose root cause before declaring the run complete.

---

## Known Limitations (Document, Don't Fix in Split 02)

- **`bq1 >= 2` for body legs:** `fill_leg` checks `bq1 > 0` not `bq1 >= 2`. For very thin books, both body fills could hit the same single-lot queue — acceptable for 1-lot testing, fix if sizing > 1 lot.
- **Time-of-day exit cutoff:** Trades entered within `max_holding_bars × bar_freq` of the session close could have their exit bar fall past `skip_close_minutes`. The current code attempts exit past the cutoff. Correct handling (force-close at cutoff) is a split 03 concern.
- **Expiry-day tau:** On Tuesday expiry sessions, `tau_years` near zero makes `iv_essvi` unreliable. The `max_expiries_per_session=1` setting means these are the primary active contracts. The engine doesn't currently block entries when `tau_years < 2h`. Flag in diagnostics, fix in split 03.
- **Forward bias on carry path:** `build_session_chain` uses futures-based forward when available. On sessions where no futures data loads, the fallback `S × exp((r−carry) × τ)` with `carry=0` ignores dividends. Acceptable for index options where dividends are in the futures basis.

---

## Implementation Order

Execute in sequence — each step builds on the previous:

0. **Add `exit_type`, `exit_fill_quality` to `ButterflyTrade`** in `portfolio/structures.py` (must be first — everything else references this)
1. **Add logging** to `engine.py` and handler to `__main__.py`
2. **Read and audit `_build_actions`** — confirm or fix the 4-cell table; record outcome
3. **Fix `orders=1` → `orders=4`** in both `estimate_transaction_cost` calls in `_simulate`
4. **Add `_fill_leg_with_fallback`** to `engine.py`
5. **Rewrite `_simulate_exit`** (two-phase logic, staleness guard, missing-row walkback)
6. **Update `_simulate` call site** to unpack the new 7-element return tuple; populate `exit_type`, `exit_fill_quality` in trade records
7. **Add `_build_nav`** to compute `cumulative_pnl` in nav output
8. **Add session error handling** and raise-on-symbol-empty check to `run()`
9. **Add per-contract bar index** in `_simulate` before candidate loop
10. **Write unit tests** for `_build_actions` and `_cashflow_from_fills`
11. **Write `scripts/smoke_test_pipeline.py`** and run it — fix any pipeline issues
12. **Run full backtest** — fix any runtime errors (no try/except wrappers on logic paths)
13. **Spot-check 5 trades** from output CSV

---

## Files Modified / Created

| File | Change |
|---|---|
| `src/essvi_bfly/backtest/engine.py` | Fix `orders=4`, rewrite `_simulate_exit`, add `_fill_leg_with_fallback`, add `_build_contract_bar_index`, add `_build_nav`, add session error handling, add logging |
| `src/essvi_bfly/portfolio/structures.py` | Add `exit_type` and `exit_fill_quality` fields to `ButterflyTrade` |
| `src/essvi_bfly/__main__.py` | Add `logging.basicConfig` handler |
| `tests/test_engine.py` | New: unit tests for `_build_actions` and `_cashflow_from_fills` |
| `scripts/smoke_test_pipeline.py` | New: data pipeline smoke test |
| `outputs/essvi_bfly/reports/butterfly_*.csv` | Generated by full run |
