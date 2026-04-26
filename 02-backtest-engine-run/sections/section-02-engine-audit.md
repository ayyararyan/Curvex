# Section 02: Engine Audit and Cashflow Fix

## Overview

This section covers two tasks that build directly on the structural prerequisites from section-01:

1. Read and audit `_build_actions` in `engine.py` — verify (or fix) the 4-leg action sequences against the required table.
2. Fix the `orders=1` → `orders=4` transaction cost bug in both `estimate_transaction_cost` call sites within `_simulate`.
3. Write unit tests in `tests/test_engine.py` covering `_build_actions` exhaustively (all 4 direction × phase combinations) and a hand-computed numerical test for `_cashflow_from_fills`.

**Depends on:** section-01  
**Blocks:** section-03, section-04

---

## Files to Modify / Create

| File | Change |
|---|---|
| `src/essvi_bfly/backtest/engine.py` | Fix `orders=1` → `orders=4` at both `estimate_transaction_cost` call sites in `_simulate` |
| `tests/test_engine.py` | Create: unit tests for `_build_actions` and `_cashflow_from_fills` |

---

## Background: The 4-Leg Action Table

| Direction | Phase | Wing Low | Body 1 | Body 2 | Wing High |
|---|---|---|---|---|---|
| LONG_BFLY | entry | BUY | SELL | SELL | BUY |
| LONG_BFLY | exit | SELL | BUY | BUY | SELL |
| SHORT_BFLY | entry | SELL | BUY | BUY | SELL |
| SHORT_BFLY | exit | BUY | SELL | SELL | BUY |

SHORT_BFLY is the exact flip of LONG_BFLY. Exit is the exact reversal of entry for the same direction. The body contract appears **twice**.

**Audit outcome (pre-confirmed):** The current implementation of `_build_actions` in `engine.py` already matches the required table exactly. No fix is needed. Record "confirmed-correct" in the git commit message.

---

## Background: Cashflow Sign Convention

```
cashflow = sum((fill.price if action == "SELL" else -fill.price) * scale)
```

SELL = positive (inflow), BUY = negative (outflow). `scale = lot_size × contract_multiplier`.

For a LONG_BFLY entry: `entry_cashflow = (2×body_price − wing_low_price − wing_high_price) × scale`

PnL formula: `pnl = entry_cashflow + exit_cashflow − total_transaction_cost`

---

## Transaction Cost Bug Fix

**Bug:** Both `estimate_transaction_cost` call sites in `_simulate` pass `orders=1`. A butterfly has 4 leg orders per event — this charges ₹20 brokerage instead of ₹80 per side (₹40 round-trip instead of ₹160).

**Fix:** Change both call sites from `orders=1` to `orders=4`.

Entry call site:
```python
entry_cost = estimate_transaction_cost(
    entry_turnover,
    self.config.fee_rate,
    self.config.tax_rate,
    self.config.leg_brokerage_per_order,
    4,   # was 1 — butterfly has 4 leg orders per entry
)
```

Exit call site — same change.

Alternatively use `orders=len(entry_fill_results)` for self-documentation.

**Note:** `_turnover_from_fills` already correctly sums absolute fill prices across all 4 fills (body counted twice). Only the `orders` argument is wrong.

---

## Tests: `tests/test_engine.py` (new file)

All tests are unit tests — no IO, no parquet loading. Use a synthetic `ButterflyCandidate` with fixed contract names `("LOW", "BODY", "HIGH")` and `pd.Series()` as placeholder quote rows.

### `_build_actions` stubs

```python
# test_build_actions_long_bfly_entry
# Assert: actions[0]==("BUY","LOW",...), [1]==("SELL","BODY",...),
#         [2]==("SELL","BODY",...), [3]==("BUY","HIGH",...)

# test_build_actions_long_bfly_exit
# Assert: actions[0]==("SELL","LOW",...), [1]==("BUY","BODY",...),
#         [2]==("BUY","BODY",...), [3]==("SELL","HIGH",...)

# test_build_actions_short_bfly_entry
# Assert: actions[0]==("SELL","LOW",...), [1]==("BUY","BODY",...),
#         [2]==("BUY","BODY",...), [3]==("SELL","HIGH",...)

# test_build_actions_short_bfly_exit
# Assert: actions[0]==("BUY","LOW",...), [1]==("SELL","BODY",...),
#         [2]==("SELL","BODY",...), [3]==("BUY","HIGH",...)

# test_build_actions_body_appears_twice (parametrize over all 4 combos)
# Assert: len([a for a in actions if a[1] == "BODY"]) == 2

# test_build_actions_contract_names_match_candidate
# Assert contract names in output match candidate fields exactly
```

### `_cashflow_from_fills` stubs

Import `FillResult` from `essvi_bfly.execution.fills`. Create synthetic fill objects with known prices.

```python
# test_cashflow_long_bfly_entry_hand_computed
# LONG_BFLY entry, scale=1.0:
#   wing_low BUY at 50  → -50
#   body SELL at 80      → +80
#   body SELL at 80      → +80
#   wing_high BUY at 50 → -50
# Expected = +60.0 (assert exact)

# test_cashflow_long_bfly_exit_hand_computed
# LONG_BFLY exit, scale=1.0:
#   wing_low SELL at 45  → +45
#   body BUY at 65        → -65
#   body BUY at 65        → -65
#   wing_high SELL at 45 → +45
# Expected = -40.0 (assert exact)

# test_cashflow_scale_applied
# Repeat entry case with scale=50 → expected = +3000.0

# test_pnl_positive_for_profitable_reversal
# entry_cashflow=60, exit_cashflow=-40, transaction_cost=10 → pnl=10 > 0

# test_transaction_cost_uses_4_orders
# Patch estimate_transaction_cost; run minimal _simulate
# Assert mock called with orders=4
```

---

## Acceptance Checklist

- [ ] `_build_actions` audit complete — "confirmed-correct" or list of cells fixed — recorded in commit message
- [ ] Both `estimate_transaction_cost` calls in `_simulate` use `orders=4`
- [ ] All 4 `test_build_actions_*` tests pass
- [ ] `test_cashflow_long_bfly_entry_hand_computed` asserts exactly +60.0
- [ ] `test_transaction_cost_uses_4_orders` verifies mock called with `orders=4`
- [ ] `uv run pytest tests/ -v` exits 0

---

## Known Limitations (Do Not Fix Here)

- `fill_leg` checks `bq1 > 0` but not `bq1 >= 2` — acceptable at 1-lot sizing.
- `_simulate_exit` discard behavior is addressed in section-03, not here.
