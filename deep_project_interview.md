# Deep Project Interview Transcript

## Project: eSSVI Butterfly Volatility Arbitrage — Backtest Implementation

---

### Requirements Source
- Strategy doc: `eSSVI Butterfly Stat-Arb Strategy.md`
- Existing code: `src/essvi_bfly/` package
- Data: `data/raw/january_2026/` — per-contract parquet files for NIFTY + BANKNIFTY

---

### Code Exploration Findings (pre-interview)

**Package structure (all modules exist):**
- `io/` — parquet loader, manifest
- `preprocess/` — bar generation, state reconstruction, option chain builder, normalizer
- `iv/` — Black-Scholes pricer, Newton+Brent IV solver
- `surface/` — eSSVI formula, calibrator with butterfly-arb constraints, diagnostics
- `signal/` — residual + market-IV computation, rolling z-scores, candidate selection
- `execution/` — fill simulation (ask/bid fill), slippage/cost model
- `portfolio/` — trade dataclass, Greeks, PnL
- `backtest/` — engine (full backtest loop), event loop, results writer

**Data:** January 2026, one parquet per contract per session date, NIFTY + BANKNIFTY.

**Known suspect code areas:**
1. `signal/candidate_selection.py` — direction assignment (`z < 0 → SHORT_BFLY`) and edge formula need careful audit against the strategy doc and standard butterfly conventions.
2. `backtest/engine.py` — action-building for LONG/SHORT butterfly, cashflow direction signs, exit simulation logic.
3. Z-score rolling window: `zscore_window_5m = 75` (= 375 min = 6.25 hours of 5-min bars) — spans across sessions, which may contaminate signals at session open.

---

### Interview Q&A

**Q: What is the primary problem with the current implementation?**
A: Both — fix known logic bugs AND get the pipeline running to produce real output.

**Q: Which scope for the backtest?**
A: NIFTY + BANKNIFTY, 5-minute bars.

**Q: What outputs are needed?**
A: Trade-level CSV, cumulative P&L / NAV curve, calibration diagnostics.

**Q: Signal direction bug — audit or skip?**
A: Audit and fix (treat it as a confirmed suspect; formally verify and correct it in the plan).

**Q: Trade sizing?**
A: 1 lot per trade (fixed single-lot; clean and debuggable).

---

### Key Decisions

- Bar frequency: **5min**
- Universe: **NIFTY + BANKNIFTY**
- Sizing: **1 lot per trade**
- Signal audit: **yes — verify direction convention, edge sign, and z-score window boundaries**
- Outputs: trade CSV, NAV curve, calibration diagnostics, summary stats
