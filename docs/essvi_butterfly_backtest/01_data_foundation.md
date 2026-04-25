# 01. Data Foundation

This step defines the minimum data model needed before any strategy logic is trustworthy.

## Objective

Build a deterministic pipeline that turns the sparse parquet events in [`data/raw/january_2026/`](/Volumes/One%20Touch/NSE/onesec/curvex/data/raw/january_2026) into time-ordered, typed, instrument-aware records.

## Inputs

- [`data/metadata/CONTRACTS_INVENTORY.csv`](/Volumes/One%20Touch/NSE/onesec/curvex/data/metadata/CONTRACTS_INVENTORY.csv)
- [`data/metadata/MANIFEST.csv`](/Volumes/One%20Touch/NSE/onesec/curvex/data/metadata/MANIFEST.csv)
- Session folders under [`data/raw/january_2026/`](/Volumes/One%20Touch/NSE/onesec/curvex/data/raw/january_2026)

## Key repo facts to encode

- One parquet file = one contract for one session.
- Rows arrive in reverse chronological order in sampled files.
- Many rows carry only one field family, for example only ask updates or only last-trade updates.
- Depth fields `bp1..bp5`, `sp1..sp5`, `bq1..bq5`, `sq1..sq5`, `bo1..bo5`, `so1..so5` are the main quote inputs.
- Index proxies available in the archive are `NIFTY50`, `NIFTYBANK`, and `SENSEX`.

## Step-by-step implementation

### 1. Build a contract master

Create `src/essvi_bfly/instruments.py`.

Implement:

- `load_contract_inventory()`
- `load_manifest()`
- `parse_contract_name(contract_name)`
- `build_session_file_map(session_date, root_symbol, expiry_code=None)`

Required normalized fields:

- `contract_name`
- `root_symbol`
- `instrument_type`
- `option_side`
- `strike`
- `expiry_code`
- `session_date`
- `relative_path`
- `exchange_hint`

### 2. Standardize path resolution

Do not hardcode file discovery by globbing the raw tree in the strategy loop.

Use the manifest as the source of truth and resolve to:

- `data/raw/january_2026/<session_date>/<file_name>`

### 3. Type all market columns explicitly

Create `src/essvi_bfly/preprocess/normalize.py`.

Implement:

- string to float conversion for price and quantity columns
- string to integer conversion where appropriate
- `timestamp` to timezone-aware pandas timestamp in `Asia/Kolkata`
- `ft` to integer epoch seconds

Expected numeric groups:

- trade: `lp`, `ltq`, `v`, `ap`, `pc`
- quote: `bp*`, `sp*`, `bq*`, `sq*`, `bo*`, `so*`
- open interest: `oi`, `poi`, `toi`
- reference fields: `o`, `h`, `l`, `c`, `uc`, `lc`, `ue`, `le`

### 4. Re-sort and de-duplicate events

Create `src/essvi_bfly/preprocess/state_reconstruction.py`.

For each file:

1. Sort ascending by `ft`, then `timestamp`.
2. Drop exact duplicates if the same event appears multiple times.
3. Preserve original row order index for auditability.

### 5. Reconstruct full quote state

This is the first hard requirement for the backtest.

For each contract-day file:

1. Forward-fill quote state within the session for all depth fields.
2. Forward-fill last known `lp`, `oi`, `tbq`, `tsq` only into a separate reconstructed-state view.
3. Keep raw events and reconstructed state as separate datasets.

Recommended outputs:

- `raw_events`
- `state_events`

`state_events` should include:

- best bid: `bp1`, `bq1`
- best ask: `sp1`, `sq1`
- depth snapshot for levels 1 to 5
- last trade snapshot
- OI snapshot
- `quote_age_seconds`
- `trade_age_seconds`

### 6. Define quality flags

Every reconstructed event should expose flags such as:

- `has_valid_bid`
- `has_valid_ask`
- `has_valid_two_sided_quote`
- `has_recent_quote`
- `has_recent_trade`
- `is_crossed_market`
- `is_zero_market`

These flags will later decide whether a strike is admissible for IV inversion.

## Deliverables

- A typed manifest loader
- A contract parser
- A state-reconstruction module
- A session-level audit report that counts:
  - contracts loaded
  - events per contract
  - percentage of events with two-sided quotes
  - percentage of bars with valid best bid and ask

## Exit criteria

You are ready for Step 2 only if you can pick any session, rebuild full quote state for a sample of NIFTY and BANKNIFTY options, and show that `bp1` and `sp1` remain coherent after forward-filling.
