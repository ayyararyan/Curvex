# Section 04: Nav Output and Session Resilience

## Overview

Two additions to `engine.py`:
1. Add `_build_nav` to compute `cumulative_pnl` column in the nav output (currently absent, causing column-mismatch on first run).
2. Wrap the session data-loading call in `run()` with a narrow `try/except` for data errors only; add end-of-run `RuntimeError` guard.

**Depends on:** section-01, section-02, section-03  
**Blocks:** section-07

---

## Tests First

Add to `tests/test_engine.py`:

### Nav tests

```python
# test_build_nav_cumulative_pnl
# _build_nav([{"trade_id":1,"pnl":10}, {"trade_id":2,"pnl":-5}, {"trade_id":3,"pnl":20}])
# → cumulative_pnl == [10, 5, 25] (sorted by trade_id)

# test_build_nav_preserves_trade_id
# DataFrame contains trade_id column with original values

# test_build_nav_integration_csv_has_cumulative_pnl(tmp_path)
# Write nav to tmp_path/butterfly_nav.csv; re-read and assert 'cumulative_pnl' in columns
```

### Session resilience tests

```python
# test_run_skips_session_on_file_not_found(monkeypatch, caplog)
# Mock build_session_chain to raise FileNotFoundError for one session, return normal data
# for a second. Assert warning in caplog; second session still processes.

# test_run_skips_session_on_oserror(monkeypatch, caplog)
# Same pattern with OSError.

# test_run_does_not_catch_keyerror_from_simulate(monkeypatch)
# Mock build_session_chain to succeed; mock _simulate to raise KeyError.
# Assert KeyError propagates unhandled out of run().

# test_run_raises_runtime_error_on_zero_rows_for_symbol(monkeypatch)
# All sessions for symbol X raise FileNotFoundError.
# Assert RuntimeError raised with message referencing the symbol.

# test_run_raises_runtime_error_on_zero_rows_all_symbols(monkeypatch)
# All sessions for all symbols fail. Assert RuntimeError.

# test_run_continues_after_data_error(monkeypatch)
# First session raises FileNotFoundError; second returns valid data.
# Assert no RuntimeError; second session data appears in output.
```

---

## Implementation

### File: `src/essvi_bfly/backtest/engine.py`

#### 1. Add `_build_nav`

```python
def _build_nav(self, nav_rows: list[dict]) -> pd.DataFrame:
    """Convert per-trade pnl list to nav DataFrame with cumulative_pnl column.

    Sorts by trade_id ascending. cumulative_pnl = cumulative sum of pnl.
    nav_rows: each dict must contain 'trade_id' and 'pnl' keys.
    Returns DataFrame with columns: trade_id, pnl, cumulative_pnl (plus extras).
    """
```

Implementation:
1. `df = pd.DataFrame(nav_rows)`
2. `df = df.sort_values("trade_id").reset_index(drop=True)`
3. `df["cumulative_pnl"] = df["pnl"].cumsum()`
4. Return `df`

Replace any existing `pd.DataFrame(nav_rows)` used to build the nav output with `self._build_nav(nav_rows)`.

#### 2. Narrow Try/Except in `run()`

Add to top of `engine.py`:
```python
from pyarrow.lib import ArrowInvalidError, ArrowIOError
```

In `run()`, wrap **only the data-loading call**:

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

The `try` block ends immediately after `build_session_chain`. Calibration, signal generation, `_simulate`, and all downstream work remain **outside** the except clause.

For calibration: `calibrate_surface` handles per-slice errors by setting `converged=False`. If it raises at session level (e.g., all slices fail with `scipy.optimize.OptimizeWarning`), add it to the catch list only if confirmed to raise (not merely warn).

#### 3. End-of-Run RuntimeError Guard

Track rows produced per symbol inside the session loop. After the loop completes:

```python
rows_produced_for_symbol: dict[str, int] = {s: 0 for s in config.root_symbols}
# (increment inside loop when session adds rows)
...
for symbol in config.root_symbols:
    if rows_produced_for_symbol[symbol] == 0:
        raise RuntimeError(
            f"Zero chain rows produced for symbol {symbol!r}. "
            "All sessions were skipped or returned empty data. "
            "Check session skip warnings above."
        )
```

Also add a combined check: if `sum(rows_produced_for_symbol.values()) == 0`, raise similarly before the per-symbol loop.

---

## Acceptance Criteria

- [ ] `_build_nav` produces `cumulative_pnl = pnl.cumsum()` sorted by `trade_id` — `test_build_nav_cumulative_pnl` passes
- [ ] `butterfly_nav.csv` written to disk contains `cumulative_pnl` column
- [ ] `run()` skips sessions on FileNotFoundError and OSError and logs warnings — tests pass
- [ ] `run()` does **not** catch `KeyError` from `_simulate` — test passes
- [ ] `run()` raises `RuntimeError` on zero rows per symbol — test passes
- [ ] `uv run pytest tests/ -v` exits 0
