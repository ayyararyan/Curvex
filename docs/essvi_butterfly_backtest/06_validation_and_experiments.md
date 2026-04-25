# 06. Validation And Experiments

This step prevents you from trusting a backtest that is mechanically wrong or overfit to January 2026.

## Objective

Verify the data pipeline, surface calibration, and trading engine before interpreting strategy performance.

## Validation checklist

### 1. Data reconstruction checks

- For 5 sample contracts, compare raw events to reconstructed quote state by hand.
- Confirm ascending event order after sorting by `ft` and `timestamp`.
- Confirm that quote forward-fill never crosses session boundaries.
- Measure the fraction of bars with valid two-sided quotes by moneyness bucket.

### 2. Pricing checks

- Re-price observed option mids from solved IVs and confirm small reconstruction error.
- Verify intrinsic-value bounds for every solved option.
- Spot-check Greeks for ATM and OTM options.

### 3. Surface checks

- Plot smile slices for several bars across one day.
- Plot time series of `theta`, `rho`, `psi` by expiry.
- Inspect calibration RMSE spikes and identify whether they are caused by stale or wide quotes.
- Reject any bar where the smile fit is obviously driven by a handful of bad strikes.

### 4. Trade-logic checks

- For 20 randomly sampled entry signals, manually inspect:
  - body strike
  - wing strikes
  - z-score
  - quote freshness
  - market butterfly premium
  - model butterfly premium
- Confirm that long and short butterfly direction matches the residual sign convention.

### 5. Backtest accounting checks

- Reconcile trade PnL from fills to portfolio NAV.
- Confirm session-end liquidation closes all structures.
- Confirm rejected trades have explicit reason codes.

## Experiment roadmap

### Phase 1. Mechanical validation

- one root symbol
- one expiry family
- one week of 5-minute data
- no hedging

### Phase 2. Base strategy benchmark

- NIFTY and BANKNIFTY
- full January 2026 sample
- 5-minute bars
- conservative filters

### Phase 3. Frequency comparison

- compare 1-minute vs 5-minute bars
- compare warm-start vs cold-start calibration
- compare spot-based vs futures-based forward proxy

### Phase 4. Sensitivity sweeps

Sweep:

- z-score entry threshold
- persistence requirement
- quote-age cutoff
- spread filter
- maximum holding bars
- cost assumptions

### Phase 5. Robustness review

Focus on:

- expiry-week behavior
- open and close auction-adjacent bars
- highly OTM strikes
- days with poor calibration coverage

## Success criteria

Treat these as research gates, not promises.

- enough bars with valid chain coverage to calibrate surfaces consistently
- residuals that are not dominated by stale quotes
- theoretical edge that survives conservative spread-crossing assumptions
- stable results when thresholds move modestly

## Immediate next coding tasks

1. Implement the manifest and contract loaders.
2. Implement per-file state reconstruction and bar sampling.
3. Build one NIFTY 5-minute chain snapshot for a single session.
4. Add IV inversion and surface calibration for one expiry.
5. Run the first manual chart review before adding trade simulation.
