# 02. Feature Pipeline

This step converts reconstructed contract-level event streams into bar-aligned option-chain snapshots.

## Objective

Create 1-minute and 5-minute chain snapshots that can feed IV inversion and eSSVI calibration.

## Why this step matters

The strategy document assumes clean chain mids at each bar. Your archive does not contain those directly. You need to manufacture them from sparse quote updates.

## Step-by-step implementation

### 1. Define the session clock

Create `src/essvi_bfly/preprocess/bars.py`.

Implement:

- exchange session calendar for the January 2026 trading dates in the archive
- canonical bar schedule for:
  - `1min`
  - `5min`
- bar-close timestamp convention

Recommendation:

- Build bars on close timestamps.
- Use the latest valid reconstructed state at or before each bar close.

### 2. Build per-contract bar snapshots

For each option file:

1. Start from `state_events`.
2. At each bar close, sample the latest state with `timestamp <= bar_close`.
3. Compute:
   - `mid = (bp1 + sp1) / 2` when both are valid
   - `spread = sp1 - bp1`
   - `spread_pct = spread / mid`
   - `microprice` if both sizes exist
   - last known `lp`
   - last known `oi`
   - quote age and trade age

Do not use `lp` as the option price if you have a valid two-sided quote. `lp` is a fallback diagnostic, not the default mark.

### 3. Build the underlying bar series

Use:

- `NIFTY50_<session>.parquet` for NIFTY options
- `NIFTYBANK_<session>.parquet` for BANKNIFTY options
- `SENSEX_<session>.parquet` for SENSEX options if you extend later

Compute bar-close underlying price from the latest valid `lp`.

Optional enhancement:

- also load the front future for the same root symbol and use futures price to estimate forwards

### 4. Calculate time to expiry

The archive gives `expiry_code`, not a fully resolved expiry timestamp.

Implement in `src/essvi_bfly/instruments.py`:

- `resolve_expiry_datetime(root_symbol, expiry_code)`

Rules:

- Month-code expiries such as `26JAN`, `26FEB`, `26MAR` should map to the actual contract expiry date and market close time.
- Numeric codes such as `26108` or `26122` should be treated as weekly expiries and resolved explicitly.
- Persist the resolved calendar in a small reference file so it is not recomputed ad hoc.

Then compute:

- `tau_years`
- `minutes_to_expiry`
- `is_same_day_expiry`

### 5. Assemble chain snapshots

Create `src/essvi_bfly/preprocess/option_chain.py`.

At each bar and expiry:

1. Gather all eligible strikes for one `root_symbol`.
2. Attach underlying spot or future.
3. Attach strike, side, expiry, and bar features.
4. Filter out contracts with:
   - invalid two-sided quote
   - stale quotes beyond the configured maximum age
   - spread too wide for the strike class
   - zero or missing `mid`

### 6. Persist intermediate data

Write chain snapshots to `outputs/essvi_bfly/intermediate/`.

Recommended partitions:

- `bar_freq=1min|5min`
- `root_symbol=NIFTY|BANKNIFTY`
- `session_date=YYYY_MM_DD`

## Minimum schema for each chain row

- `session_date`
- `bar_close`
- `root_symbol`
- `contract_name`
- `option_side`
- `strike`
- `expiry_code`
- `tau_years`
- `underlying_price`
- `bp1`
- `sp1`
- `mid`
- `spread`
- `spread_pct`
- `lp`
- `oi`
- `quote_age_seconds`
- `trade_age_seconds`

## Exit criteria

You are ready for Step 3 only if you can materialize one full 1-minute chain for NIFTY and BANKNIFTY, inspect one bar manually, and verify that the selected option prices came from recent reconstructed quotes rather than stale last-trade prints.
