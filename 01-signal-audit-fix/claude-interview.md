# Interview Transcript — Signal Audit & Fix (Split 01)

## Q1 — min_periods after session-boundary fix

**Question:** Research confirmed direction and edge are already correct. The real bug is the rolling window grouping by `contract_name` only — it should group by `(contract_name, session_date)`. After that fix, the first `min(20, window)` bars of EVERY session will be NaN. Should `min_periods` stay at `min(20, window) = 20` bars (100-min warmup per session), or should it be raised to the full window (75 bars = full-session warmup)?

**Answer:** Keep min_periods = min(20, window) = 20 (signal activates after 100-min warmup; partial-window estimates accepted for early-session bars).

## Q2 — Test directory location

**Question:** Where should `tests/` go?

**Answer:** Top-level `tests/` at project root (standard pytest layout: `/tests/test_signal.py` alongside `src/`).

## Q3 — Fix scope

**Question:** The spec only targets butterfly signal. Should the same session-boundary fix also be applied to `zscores.py`'s persistence counter and `straddle_selection.py`, or butterfly-only for now?

**Answer:** Fix both z-score rolling AND persistence counter in `zscores.py`, butterfly signal only. Leave `straddle_selection.py` for a separate split.

---

## Summary of Decisions

| Topic | Decision |
|---|---|
| Direction assignment (z < 0 → SHORT_BFLY) | **Correct** — add 3-line clarifying comment, no code change |
| Edge formula | **Correct** — no change |
| Rolling window session boundary | **Fix** — group by `(contract_name, session_date)` |
| Persistence counter session boundary | **Fix** — same groupby change |
| min_periods | **Keep** at `min(20, window)` |
| Test location | `tests/test_signal.py` at project root |
| Straddle scope | Out of scope for this split |
