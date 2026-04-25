# TDD Plan — Signal Audit & Fix (Split 01)

## Testing Context

Framework: pytest ≥ 8.0 (new addition to this project — no existing tests).
Location: `tests/test_signal.py` at project root.
Run command: `pytest tests/` (with `pythonpath = ["src"]` in `pyproject.toml`).
No existing fixtures, mocking patterns, or conftest.py to follow.

---

## Tests Before Change 1 — Direction Assignment Comments

Change 1 is comment-only (no code change). However, the comment makes a verifiable claim: that LONG_BFLY in `engine.py` means BUY wings + SELL body. Write the smoke test first, then add the comment.

```python
# Test: test_build_actions_long_bfly_convention
#   Import _build_actions (or BacktestEngine) with direction="LONG_BFLY", is_exit=False
#   Assert action list is: [(BUY, wing_low), (SELL, body), (SELL, body), (BUY, wing_high)]
#   This guards the audit verdict against engine drift
```

---

## Tests Before Change 2 — Session-Boundary Fix in zscores.py

Write these tests against the CURRENT (broken) code first to demonstrate the bug, then run them against the fixed code to confirm the fix. Each test must fail before the fix and pass after.

**Sub-change 2b/2c: Rolling z-score and persistence counter**

```python
# Test: test_zscore_rolling_within_session
#   Build two-session synthetic panel (single contract, 30 bars each, window=10)
#   Assert session 2 bars 0-8 have NaN zscore (fails before fix; passes after)
#   Assert session 2 bar 9+ has finite zscore
#   Assert same_sign_persistence has no NaN values (tests .reindex guard)

# Test: test_persistence_counter (Case A — sign flip)
#   Input [1.2, 1.5, -1.3, -1.8, -2.0, NaN] → expected [1, 2, 1, 2, 3, 0]
#   Calls persistence() directly; pure unit test, not affected by groupby change

# Test: test_persistence_counter (Case B — leading NaN)
#   Input [NaN, NaN, 1.5, 1.8, NaN, 2.0] → expected [0, 0, 1, 2, 0, 1]
#   Validates session-open behavior where z-scores start as NaN
```

---

## Tests Before Change 3 — Pytest Setup

No behavioral tests needed. The act of running `pytest` after adding `pyproject.toml` entries verifies the setup. If pytest is not yet installed, `uv sync --group dev` (or equivalent) will install it.

---

## Tests Before Change 4 — candidate_selection.py Direction and Edge

These tests use the existing (unchanged) `select_candidates` code — they verify it does the right thing. Write them before touching the file; if any fail, that indicates a real bug not caught by the audit.

```python
# Test: test_direction_long_bfly
#   Synthetic chain with body zscore=+2.0, persistence=3, iv_market > iv_essvi
#   Call select_candidates; assert returned candidate direction == "LONG_BFLY"

# Test: test_direction_short_bfly
#   Synthetic chain with body zscore=-2.0, persistence=3, iv_market < iv_essvi
#   Call select_candidates; assert returned candidate direction == "SHORT_BFLY"

# Test: test_edge_long_bfly_positive
#   LONG_BFLY scenario where iv_market > iv_essvi for body
#   Assert theoretical_edge > 0 (structure is cheap relative to fair value)

# Test: test_edge_short_bfly_positive
#   SHORT_BFLY scenario where iv_market < iv_essvi for body
#   Assert theoretical_edge > 0 (structure is expensive relative to fair value)
```

---

## Test Writing Order (Recommended)

1. `test_build_actions_long_bfly_convention` — baseline smoke test, fast to write
2. `test_persistence_counter` (both cases) — pure function test, no DataFrame setup
3. `test_zscore_rolling_within_session` — demonstrates the bug, confirms the fix
4. `test_direction_long_bfly` + `test_direction_short_bfly` — direction audit confirmation
5. `test_edge_long_bfly_positive` + `test_edge_short_bfly_positive` — edge audit confirmation

All tests in (1) and (2) are independent of the Change 2 fix — they should pass both before and after. All tests in (3) must fail before Change 2 and pass after.

---

## Shared Fixture Pattern

Rather than repeating synthetic DataFrame construction in each of the four candidate-selection tests, define a `make_butterfly_chain(zscore, iv_market, iv_essvi)` factory helper in the test file. It returns a minimal 3-row chain DataFrame with the required columns at known values, plus a 1-row diagnostics DataFrame. The factory accepts zscore and IV values as parameters; everything else is fixed at non-filtering defaults.

```python
# Helper (not a pytest fixture — just a local function):
# def make_butterfly_chain(body_zscore, body_iv_market, body_iv_essvi,
#                          persistence=3, lot_size=1, contract_multiplier=1)
#     → (chain_df, diagnostics_df, config)
#   Sets: wing_low/body/wing_high rows with equidistant strikes
#   Sets: enforce_otm_structure_side=False in config for simplicity
#   Sets: all quote_ok=True, spread=small, tau_years=0.1, forward=18000
#   Sets: body zscore and iv values per arguments; wing values set to neutral
```
