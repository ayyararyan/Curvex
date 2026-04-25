# Section 03 — Candidate Selection Comments

## Overview

This section makes a **comment-only** change to one file. No code logic changes, no new imports, no changes to function signatures or return types. The section is complete once the comment block is added.

**File to modify:** `src/essvi_bfly/signal/candidate_selection.py`

**Depends on:** Nothing (parallelizable with sections 01 and 02).

**Blocks:** section-04 (the test suite references this audit verdict when writing `test_build_actions_long_bfly_convention`).

---

## Tests for This Section

This section makes no code changes, so there are no behavioral tests that can fail/pass on it directly. The audit claim it documents is guarded by `test_build_actions_long_bfly_convention` in section-04. That test is specified there; do not write it here.

The relationship is: write the comment first (this section), then the test in section-04 will confirm the claim is accurate. If the test in section-04 fails, the comment is wrong and must be corrected.

---

## Background and Audit Verdict

The `select_candidates` function assigns direction at approximately lines 73–78 of `candidate_selection.py`:

```python
if body["zscore"] < 0:
    direction = "SHORT_BFLY"
    edge = market_premium - model_premium
else:
    direction = "LONG_BFLY"
    edge = model_premium - market_premium
```

The economic logic:

- **Negative z-score** means `residual_iv = iv_market − iv_essvi` is below its rolling mean. The body option's implied volatility is **below** the eSSVI surface — the body is **underpriced**. The correct trade is **SHORT_BFLY**: buy the cheap body, sell the wings.
- **Positive z-score** means the body IV is **above** the surface — the body is **overpriced**. The correct trade is **LONG_BFLY**: sell the overpriced body, buy the wings.

This mapping has been audited and confirmed correct. It is consistent with `engine.py._build_actions`, where LONG_BFLY entry executes:

```
BUY wing_low  +  SELL body × 2  +  BUY wing_high
```

This matches the standard industry definition of a long butterfly (long the outer strikes, short the middle strike twice). Reference: CME Group butterfly convention and Hull's *Options, Futures, and Other Derivatives*.

**The z = 0 edge case:** `zscore == 0.0` never reaches the direction branch in practice. The filter `if abs(body["zscore"]) < config.entry_z: continue` (which appears before the direction assignment) filters out any row where the absolute z-score is below `entry_z`. Since `entry_z` is a positive threshold (typically 1.5), a z-score of exactly 0.0 is filtered before direction assignment. The `else: direction = "LONG_BFLY"` branch theoretically captures `z ≥ 0`, but `z = 0` will never arrive there.

---

## Implementation: What to Do

### Add a comment block in `select_candidates`

**Location:** `src/essvi_bfly/signal/candidate_selection.py`

**Insertion point:** Immediately after the `def select_candidates(...)` function definition opening, before the first executable line (`diag_ok = diagnostics[...]` or similar). The comment should be the first content inside the function body.

Add the following comment block (indented at the function body level, 4 spaces):

```python
    # Direction mapping (audit-verified): z < 0 → SHORT_BFLY (buy underpriced body,
    # sell wings); z >= 0 → LONG_BFLY (sell overpriced body, buy wings). Consistent
    # with engine.py._build_actions: LONG_BFLY entry = BUY wing_low + SELL body × 2
    # + BUY wing_high (standard industry convention). z = 0 never reaches this branch
    # in practice — filtered upstream by `abs(z) < entry_z` before direction is assigned.
```

The comment covers all three required points:
1. The direction mapping with economic rationale.
2. Consistency with `engine.py._build_actions` and the specific action order.
3. The z = 0 edge case and why it never arrives here in practice.

---

## Verification

After adding the comment, confirm:
- The function signature (`def select_candidates(chain, diagnostics, config)`) is unchanged.
- The return type annotation (`-> ...`) is unchanged if it existed.
- No new imports at the top of the file.
- No changes to any logic line.
- No changes to `_structure_value`, `ButterflyCandidate`, or any other function in the file.

---

## Non-Changes (Explicitly Out of Scope)

- Do NOT change any logic in `candidate_selection.py`.
- Do NOT add imports.
- Do NOT modify `engine.py`, `zscores.py`, `config.py`, or any other file.
- Do NOT add a docstring to `select_candidates` — only a comment block inside the function body.
