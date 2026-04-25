# Interview Transcript — Split 02 Backtest Engine & End-to-End Run

---

## Q1: Is Split 01 (signal module corrections) already applied to the codebase?

**Answer:** Split 01 is already merged — start from corrected signal.

The direction inversion and edge calculation bugs in `candidate_selection.py` have already been fixed. Split 02 planning proceeds against the corrected signal module state.

---

## Q2: The spec flags `_simulate_exit` returns None when no bar in max_holding_bars yields a fill — those trades are discarded. What should we do?

**Answer:** Add time-stop: force exit at last available bar quote.

More realistic for NIFTY/BANKNIFTY which are highly liquid. Use whatever quote is available at the `max_holding_bars` bar rather than discarding the trade entirely. This avoids artificially filtering out trades that simply didn't revert within the holding window.

---

## Q3: For the time-stop exit (forced at max_holding_bars): if the target bar has no valid two-sided quote for one or more legs, what fallback fill price?

**Answer:** Use last-traded price (lp) as fallback fill price.

Realistic for liquid index options — `lp` is usually very close to fair value even if the quote is stale at that particular bar. This avoids phantom-fill scenarios while still recording the trade.

---

## Q4: When an entire session fails, should the engine abort or continue?

**Answer:** Log warning and skip session, continue to next.

Allows partial runs. Output CSVs will contain whatever sessions succeeded. Missing a session due to a data problem is acceptable and should not prevent all other sessions from running.

---

## Q5: Are there specific failure modes that should be warnings vs hard errors?

**Answer:** Only data-loading errors (missing file, schema mismatch) can be skipped; logic errors must crash.

Missing a session file is acceptable. Bugs in engine logic (e.g., NaN cashflows, divide-by-zero in z-score, unexpected column absence after calibration) must raise immediately — wrapping these with try/except is explicitly prohibited.

---

## Q6: Should the smoke-test script write any files, or just print to stdout?

**Answer:** Print to stdout only — pass/fail assertions.

CI-friendly format. No output artifacts. The script runs `build_session_chain` for one session and asserts: chain non-empty, tau_years > 0 for all rows, mid > 0 for liquid strikes, forward non-null and close to spot, quote_ok ≥ 50% of rows.
