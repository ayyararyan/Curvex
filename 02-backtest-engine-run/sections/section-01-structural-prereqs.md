# Section 01: Structural Prerequisites

## Overview

This section establishes the two structural prerequisites that all subsequent engine-modification sections depend on:

1. Add `exit_type` and `exit_fill_quality` fields to `ButterflyTrade` in `src/essvi_bfly/portfolio/structures.py`
2. Add a module-level logger to `src/essvi_bfly/backtest/engine.py`
3. Add a stderr logging handler in `src/essvi_bfly/__main__.py`

**No automated tests are required for this section** beyond confirming that existing imports remain clean (`uv run pytest tests/ -v` should still pass after these changes).

**Blocks:** sections 02, 03, 04, 05 — every engine modification references the new `ButterflyTrade` fields and logger.

**Depends on:** nothing.

---

## Implementation Order

Complete in this exact sequence so that later sections never encounter missing attributes:

1. Add fields to `ButterflyTrade` (structures.py)
2. Add logger to engine.py
3. Add handler to `__main__.py`

---

## File 1: `src/essvi_bfly/portfolio/structures.py`

**Current state:** `ButterflyTrade` is a `@dataclass(slots=True)` with these fields (in order):
`trade_id`, `root_symbol`, `expiry_code`, `direction`, `entry_bar`, `body_contract`, `wing_low_contract`, `wing_high_contract`, `option_side`, `entry_zscore`, `entry_cost`, `exit_bar`, `exit_zscore`, `lot_size`, `contract_multiplier`, `status`.

**Change:** Append two new optional fields with `None` defaults **after** `status`. Because the dataclass uses `slots=True`, every new field must have a default — placing them at the end preserves positional construction compatibility.

```python
exit_type: str | None = None
# Allowed values: 'profit_take' | 'stop_loss' | 'time_stop' | 'time_stop_no_quote'

exit_fill_quality: str | None = None
# Allowed values: None (normal) | 'degraded' (stale lp used at time-stop)
```

These fields are populated by `_simulate_exit` (section 03) and propagated through `_simulate`'s trade-record construction. Before section 03 is implemented they will remain `None` for all trades — which is the correct default.

**Verification:** After the edit, run:
```bash
python -c "from essvi_bfly.portfolio.structures import ButterflyTrade; t = ButterflyTrade.__dataclass_fields__; assert 'exit_type' in t and 'exit_fill_quality' in t"
```

---

## File 2: `src/essvi_bfly/backtest/engine.py`

**Current state:** The file has no `import logging` and no module-level logger.

**Change:** Add two lines in the imports block, after the stdlib imports and before the first third-party import:

```python
import logging
```

Then, after the imports (before the `class BacktestEngine` definition), add:

```python
logger = logging.getLogger(__name__)
```

The `__name__` here resolves to `"essvi_bfly.backtest.engine"`. The logger is used in section 04 in `run()` for session-skip warnings.

**Nothing else changes in engine.py in this section.**

---

## File 3: `src/essvi_bfly/__main__.py`

**Current state:** The file imports `argparse`, `run_backtest`, and `BacktestConfig`. No logging configured.

**Change:** Add `import logging` and `import sys` in the stdlib imports, then call `logging.basicConfig` as the first line inside `main()`, before argument parsing:

```python
import logging
import sys
```

Inside `main()`, before `parser = argparse.ArgumentParser(...)`:

```python
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
```

If `scripts/run_backtest.py` has its own `main()` guard that bypasses `__main__.py`, add the same `basicConfig` call there.

---

## Acceptance Checklist

- [ ] `ButterflyTrade` has `exit_type: str | None = None` and `exit_fill_quality: str | None = None` as the last two fields
- [ ] `engine.py` has `import logging` and `logger = logging.getLogger(__name__)` at module level
- [ ] `__main__.py` has `logging.basicConfig(level=logging.INFO, stream=sys.stderr, ...)` at the start of `main()`
- [ ] `uv run pytest tests/ -v` passes (no import errors, no broken dataclass construction in existing tests)
- [ ] `python -c "from essvi_bfly.portfolio.structures import ButterflyTrade"` exits without error
