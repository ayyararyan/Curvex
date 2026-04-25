# 04. Trade Logic

This step turns residuals into discrete butterfly structures and portfolio actions.

## Objective

Create deterministic rules for candidate selection, butterfly construction, entry, exit, and risk gating.

## Step-by-step implementation

### 1. Define eligible expiries

Start narrow.

Recommended first pass:

- NIFTY and BANKNIFTY only
- 5-minute bars first
- nearest non-expiry-day weekly or monthly expiry
- skip first 15 minutes and final 15 minutes of the session

### 2. Convert z-scores into directional views

In `src/essvi_bfly/signal/candidate_selection.py`:

- `zscore > entry_threshold` -> short butterfly candidate
- `zscore < -entry_threshold` -> long butterfly candidate

Require:

- same-sign persistence for at least `2` bars on 5-minute data or `3` bars on 1-minute data
- valid calibration diagnostics
- valid two-sided quotes on body and both wings

### 3. Select butterfly geometry

For each body strike `K2`:

1. Pick symmetric wing spacing from the exchange strike grid.
2. Use `K1 = K2 - dK` and `K3 = K2 + dK`.
3. Require all three strikes to exist in the same expiry and same option side.

Initial implementation choice:

- same-side call butterflies only for all strikes above ATM
- same-side put butterflies only for all strikes below ATM

This avoids mixing call and put parity complications in the first version.

### 4. Mark theoretical edge

For each candidate butterfly, compute:

- market net premium from reconstructed mids
- model net premium from eSSVI IVs re-priced through Black-Scholes
- edge in currency terms
- edge normalized by estimated round-trip cost

Trade only if:

- absolute z-score is above threshold
- theoretical edge is positive after costs
- all three legs meet spread and freshness limits

### 5. Define entry and exit rules

Suggested initial rules:

- Entry:
  - `abs(zscore) >= 1.5`
  - persistence satisfied
  - calibration RMSE below threshold
- Exit:
  - `abs(zscore) <= 0.5`
  - time stop reached
  - vol-stop reached
  - session-end liquidation

### 6. Add trade-level risk limits

Per trade:

- max loss from structure premium
- max acceptable spread cost
- max stale-quote age
- reject if one leg carries zero displayed size

Portfolio-level:

- cap concurrent butterflies per underlying
- cap net delta
- cap net vega
- cap short-gamma exposure into expiry

### 7. Encode state transitions

Represent each trade as:

- `PENDING`
- `OPEN`
- `PARTIALLY_EXITED`
- `CLOSED`
- `CANCELLED`

This makes the simulator realistic enough for legged fills later.

## Deliverables

- candidate selector
- butterfly constructor
- trade rule config
- trade state machine

## Exit criteria

You are ready for Step 5 only if the strategy can take one day of bar-level residuals, generate valid butterfly candidates, and reject malformed structures where one wing is missing, stale, or too wide.
