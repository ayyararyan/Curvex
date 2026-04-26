# Section 06: Smoke-Test Script

## Overview

Create `scripts/smoke_test_pipeline.py` — a lightweight data-pipeline gate that validates a single session before committing to a full 21-session run. Runs 11 independent checks, prints PASS/FAIL for each, exits 0 on all pass or 1 on any failure.

**Depends on:** section-01 (logging handler in `__main__.py`)  
**Parallelizable with:** sections 02–05 (no dependency on engine modifications)  
**Blocks:** section-07

---

## Files to Create / Modify

| File | Change |
|---|---|
| `scripts/smoke_test_pipeline.py` | New: 11-check smoke-test script |
| `tests/test_engine.py` | Append: unit tests for `check()` helper and exit-code behavior |

---

## Tests First

Add to `tests/test_engine.py`:

```python
# test_check_helper_prints_pass_when_true
# check("label", True, "detail") prints a line containing "PASS"

# test_check_helper_prints_fail_when_false
# check("label", False) prints a line containing "FAIL"

# test_check_helper_returns_true_on_pass
# check("label", True) returns True

# test_check_helper_returns_false_on_fail
# check("label", False) returns False

# test_main_exits_1_when_any_check_fails
# Mock build_session_chain to return a chain where one check will fail (e.g. tau_years=0 for some rows)
# pytest.raises(SystemExit) with code 1

# test_main_exits_0_when_all_checks_pass
# Mock build_session_chain to return a minimal valid chain satisfying all 11 checks
# pytest.raises(SystemExit) with code 0
```

---

## Implementation: `scripts/smoke_test_pipeline.py`

### CLI Flags

```
--session             Session date string (default: "2026_01_02")
--symbol              Root symbol (default: "NIFTY")
--rmse-limit-override Float override for calibration RMSE limit check (default: from config)
```

Parse with `argparse`.

### Function Stubs

```python
def check(label: str, condition: bool, detail: str = "") -> bool:
    """Print PASS/FAIL line with detail. Returns True if passed."""

def main() -> None:
    """Run 11 smoke checks for (session, symbol). Exit 0=all pass, 1=any fail."""
```

### Behavior Contract

- All 11 checks run independently, even if early ones fail.
- Each check prints: `PASS: <label>  <detail>` or `FAIL: <label>  <detail>`
- `main()` calls `sys.exit(0)` if all passed, `sys.exit(1)` otherwise.

### The 11 Checks

After calling `build_session_chain` (and `calibrate_surface` for diagnostics):

1. **Chain non-empty** — `len(chain) > 0`

2. **Tau positivity** — `(chain["tau_years"] > 0).all()`  
   Detail: print count of zero/negative rows if any

3. **ATM mid prices** — for rows where `abs(log(strike/forward)) <= 0.03`, all `mid > 0`  
   Detail: print ATM row count and fail count

4. **Forward quality** — `forward` is non-null for every row AND at each `bar_close`, `abs(forward / spot - 1) <= 0.01`  
   Detail: print max deviation found

5. **Quote coverage** — `quote_ok == True` for ≥ 50% of rows  
   Detail: print actual percentage

6. **Calibration convergence** — at least 3 slices with `converged == True` in diagnostics (filtered by `rmse <= rmse_limit_override` if flag provided)  
   Detail: print converged count / total slices

7. **Bar count** — every unique `contract_name` has ≥ 60 rows in the chain  
   Detail: print contract with minimum bar count

8. **Strike coverage** — at least 5 distinct strikes within ATM ±5% per expiry (`abs(log(strike/forward)) <= 0.05`)  
   Detail: print expiry with minimum strike count

9. **No duplicate index keys** — no duplicate `(bar_close, contract_name)` pairs  
   Detail: print count of duplicates if any

10. **Underlying contract resolved** — `config.underlying_spot_map[symbol]` exists in manifest for this session and has non-empty data  
    Detail: print the contract name looked up

11. **Session-boundary z-score NaN guard** — first `config.zscore_window_5m` (75) rows per contract (sorted by `bar_close`) are all `zscore == NaN`  
    Detail: print count of non-NaN values in first 75 rows if any (should be 0)

---

## Running the Script

After implementation, run:

```bash
cd /Volumes/One\ Touch/NSE/onesec/curvex
uv run python scripts/smoke_test_pipeline.py --session 2026_01_02 --symbol NIFTY
```

Expected output on a clean pipeline: 11 lines all starting with `PASS:`. Any `FAIL:` line must be resolved before running section-07.

---

## Acceptance Checklist

- [ ] `scripts/smoke_test_pipeline.py` exists and is executable via `uv run python scripts/smoke_test_pipeline.py`
- [ ] `check()` unit tests pass
- [ ] Script exits with code 1 when at least one check fails (test passes)
- [ ] Script exits with code 0 when all 11 checks pass against a valid session
- [ ] Running against `2026_01_02 / NIFTY` exits 0 (pre-condition for section-07)
