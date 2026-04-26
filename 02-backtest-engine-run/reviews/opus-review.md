# Opus Review — Split 02 Backtest Engine & End-to-End Run

**Plan reviewed:** `claude-plan.md`
**Cross-referenced:** spec.md, claude-spec.md, claude-interview.md, claude-research.md, engine.py

---

## Summary

The plan is well-structured and the conceptual approach is sound. Most of what the plan describes as "audit" is accurate against the current code — the action sequences and cashflow formula in `engine.py` already match what the plan says they should be. The most important real change is replacing the discard-on-no-fill in `_simulate_exit` with a time-stop that uses `lp` fallback. There are, however, a number of concrete bugs, ambiguities, and missing considerations the plan needs to address before implementation begins.

---

## Critical Bugs Found

### 1. `orders=1` Bug in Transaction Cost (HIGH)
`estimate_transaction_cost` is called with `orders=1` at both entry and exit (engine.py lines 127, 144). But a butterfly has 4 leg orders per side. The plan says ₹80/side (4 × ₹20) but the code charges ₹20/side. Fix: pass `orders=4` (or `orders=len(fill_results)`).

### 2. `ButterflyTrade` Missing `exit_type` Field
`portfolio/structures.py` `ButterflyTrade` has no `exit_type` field. Adding it to trades DataFrame will fail `asdict(trade)`. Must add `exit_type: str | None = None` to the dataclass before anything else.

### 3. `cumulative_pnl` Missing from Output
`_simulate` builds `nav_rows` with per-trade `pnl`, but `butterfly_nav.csv` column `cumulative_pnl` is not computed anywhere — causes column-mismatch on first run.

### 4. `lp` Fallback PnL Bias
Using raw `lp` for both BUY and SELL legs at time-stop ignores the bid-ask spread entirely. Time-stop trades will appear spuriously profitable. Need a synthetic spread adjustment: BUY at `lp × (1 + half_spread)`, SELL at `lp × (1 - half_spread)`. Also need a staleness guard on `lp`.

### 5. Missing Wing Row at Time-Stop (Silently Returns None)
If a wing contract has no row in `chain_index` at the time-stop bar, `_get_leg_open_quotes` returns None and the time-stop silently falls through, defeating the whole point. Must specify fallback behavior (walk back to most recent valid bar, or record as `time_stop_no_quote`).

---

## Action Items Integrated Into Plan

1. Fix `orders=1` → `orders=4` in `estimate_transaction_cost` calls
2. Add `exit_type: str | None` and `exit_fill_quality: str | None` to `ButterflyTrade`
3. Add `cumulative_pnl` computation to `_simulate` or `write_results`
4. Add staleness guard + spread penalty for `lp` fallback fills
5. Specify missing-wing-row behavior at time-stop bar
6. Add logging module setup (`engine.py` + handler in `__main__.py`)
7. Exit type priority: `stop_loss` wins over `profit_take` at same bar
8. Add unit tests for `_build_actions` and `_cashflow_from_fills`
9. Extend error catch list (`ArrowIOError`, `OSError`, `EmptyDataError`)
10. Raise if all sessions for a single root symbol fail
11. Add calibration failure handling note
12. Additional smoke-test checks (bar count, strike coverage, duplicate keys)
13. Session-boundary z-score regression check in smoke test
14. Add per-contract bar-index cache (O(N²) concern in candidate loop)
15. Add `portfolio/structures.py` to files modified list
16. Fix plan prose issues (typo, contradictory passage)

---

## Items NOT Integrated (deferred or out of scope)

- **Random seed for scipy:** Optimizers with fixed initial guess are deterministic; not a practical risk for split 02.
- **Concurrent positions cap:** Risk management policy — out of scope for this split, belongs in split 03 parameter tuning.
- **Expiry-day / end-of-session exit cutoff:** Complex edge case; note as known limitation, do not redesign the engine for it in split 02.
- **Forward/dividend yield bias:** Existing code uses futures-based forward when available; bias applies only on fallback S×exp(rτ) path. Note as known limitation.
- **`--run-tag` CLI flag:** Output overwrite policy simplified to: run creates/overwrites the reports directory. Implement `--run-tag` in split 03 if needed.
- **`bq1 >= 2` body lot check:** Acceptable known limitation at 1-lot level; document in commit message.
