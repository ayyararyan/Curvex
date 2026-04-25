# 05. Backtest Engine

This step turns the trade rules into a realistic simulator with fills, PnL, and portfolio accounting.

## Objective

Simulate the strategy bar by bar using reconstructed quotes instead of idealized fills.

## Step-by-step implementation

### 1. Create the event loop

Create:

- `src/essvi_bfly/backtest/event_loop.py`
- `src/essvi_bfly/backtest/engine.py`

Core loop per bar:

1. load current chain snapshot
2. load current surface calibration
3. update open positions marks and Greeks
4. evaluate exits first
5. evaluate new entries second
6. simulate orders and fills
7. update portfolio state

### 2. Implement the fill model

Create:

- `src/essvi_bfly/execution/fills.py`
- `src/essvi_bfly/execution/slippage.py`

Initial conservative assumptions:

- buy fills at ask
- sell fills at bid
- optional improvement factor based on half-spread participation
- reject fills if displayed size at best level is zero

Second-pass enhancement:

- consume displayed level-1 size
- partial fill residual size spills into later bars

### 3. Simulate butterfly entry

Do not assume atomic 4-leg execution in version 1.

Instead:

- model all legs as separate child orders submitted on the same bar
- fill each leg independently using current bar quotes
- if one or more legs fail, either:
  - cancel the entire structure, or
  - carry a temporary incomplete structure with explicit exposure flags

Version-1 recommendation:

- require all legs to fill on the same bar
- otherwise cancel the candidate

This is less realistic but safer for the first benchmark.

### 4. Mark portfolio PnL

Create `src/essvi_bfly/portfolio/pnl.py`.

Track:

- realized PnL
- unrealized mark-to-market PnL
- spread cost paid
- fees and taxes
- max adverse excursion
- max favorable excursion

Mark open legs using conservative side-specific marks:

- long positions marked to bid
- short positions marked to ask

### 5. Aggregate Greeks and hedges

At every bar, compute:

- portfolio delta
- gamma
- vega
- theta

For version 1:

- record hedge need but do not auto-hedge

For version 2:

- simulate delta hedge using the front future

### 6. Persist full audit trails

Create `src/essvi_bfly/backtest/results.py`.

Write:

- orders table
- fills table
- positions table
- per-bar portfolio NAV
- per-trade lifecycle table
- rejected-candidate reason table

## Cost model to encode

Include:

- brokerage
- exchange fees
- statutory taxes
- spread crossing cost

Store all cost assumptions in `src/essvi_bfly/config.py` so you can stress them easily.

## Deliverables

- event-driven backtest loop
- fill simulator
- portfolio accounting module
- reproducible outputs in `outputs/essvi_bfly/reports/`

## Exit criteria

You are ready for Step 6 only if one test session can run end to end from chain snapshot to final trade log without manual intervention, and the generated PnL can be reconciled to leg-level fills.
