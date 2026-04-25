# 03. Surface And Residuals

This step adds implied-vol inversion, eSSVI calibration, and the residual signal layer.

## Objective

Produce an arbitrage-aware per-bar volatility surface and standardized mispricing residuals by strike and expiry.

## Step-by-step implementation

### 1. Implement Black-Scholes pricing and Greeks

Create:

- `src/essvi_bfly/iv/black_scholes.py`
- `src/essvi_bfly/portfolio/greeks.py`

Support:

- option price
- delta
- gamma
- vega
- theta

Inputs:

- spot or forward
- strike
- tau
- rate
- dividend yield if used
- implied vol
- option side

### 2. Implement implied-vol inversion

Create `src/essvi_bfly/iv/implied_vol.py`.

Use:

- Newton-Raphson as primary solver
- Brent fallback

Per-row inputs:

- bar-close option `mid`
- underlying price
- strike
- `tau_years`
- option side

Filter before inversion:

- invalid or crossed quote
- `mid <= intrinsic_value`
- quote older than the configured max age
- spread above threshold

Store diagnostics:

- `iv_market`
- `iv_solver_status`
- `iv_solver_iterations`
- `iv_input_price_source`

### 3. Define moneyness coordinates

eSSVI is more stable in log-moneyness.

Add:

- `k = ln(K / F)`
- `total_variance = iv_market^2 * tau`

Use a forward proxy:

- first choice: front future aligned to the expiry family when available
- fallback: underlying index spot adjusted by a simple carry model

### 4. Implement eSSVI slice calibration

Create:

- `src/essvi_bfly/surface/essvi.py`
- `src/essvi_bfly/surface/calibrate.py`
- `src/essvi_bfly/surface/diagnostics.py`

Per bar and expiry:

1. Select eligible strikes.
2. Weight observations by:
   - inverse spread
   - recent quote freshness
   - closeness to ATM
3. Warm-start from the previous bar.
4. Enforce:
   - positive `theta`
   - `rho` inside `(-1, 1)`
   - butterfly no-arb constraint
5. Emit:
   - calibrated parameters
   - fit RMSE
   - strike count used
   - convergence flag

### 5. Add surface evaluation

For every eligible chain row:

- `iv_essvi`
- `tv_essvi`
- `residual_iv = iv_market - iv_essvi`

### 6. Standardize residuals into z-scores

Create:

- `src/essvi_bfly/signal/residuals.py`
- `src/essvi_bfly/signal/zscores.py`

Recommended keys for rolling windows:

- `root_symbol`
- `expiry_code`
- `contract_name`

Suggested initial windows:

- `30` bars for 1-minute
- `12` bars for 5-minute

Required outputs:

- `residual_mean_roll`
- `residual_std_roll`
- `zscore`
- `same_sign_persistence`

### 7. Add model-quality gates

Do not let bad calibrations generate trades.

Reject a bar or slice if:

- calibration did not converge
- too few strikes survived filters
- surface RMSE is above threshold
- ATM forward proxy is missing

## Deliverables

- IV inversion module
- eSSVI calibrator
- surface diagnostics table per bar and expiry
- residual and z-score table per contract-bar

## Exit criteria

You are ready for Step 4 only if you can plot one day of NIFTY or BANKNIFTY per-bar calibration outputs and verify that large z-scores coincide with visible local deviations from the fitted smile rather than solver failures or stale quotes.
