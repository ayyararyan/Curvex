# eSSVI Butterfly Backtest Implementation Pack

This folder turns [`eSSVI Butterfly Stat-Arb Strategy.md`](/Volumes/One%20Touch/NSE/onesec/curvex/eSSVI%20Butterfly%20Stat-Arb%20Strategy.md) into a repo-specific build plan for your January 2026 intraday options archive in [`data/`](/Volumes/One%20Touch/NSE/onesec/curvex/data).

## What makes this repo different from the strategy note

- The raw files are sparse event/snapshot parquet files, not clean chain snapshots.
- Most numeric fields are stored as strings and many rows update only a subset of columns.
- Bid/ask state is present through depth fields such as `bp1` and `sp1`, but often arrives as partial updates that must be reconstructed.
- The correct first milestone is a state-reconstruction pipeline, not immediate IV inversion.

## Suggested build order

1. Read [01_data_foundation.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/01_data_foundation.md)
2. Implement [02_feature_pipeline.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/02_feature_pipeline.md)
3. Implement [03_surface_and_residuals.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/03_surface_and_residuals.md)
4. Implement [04_trade_logic.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/04_trade_logic.md)
5. Implement [05_backtest_engine.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/05_backtest_engine.md)
6. Run the checks in [06_validation_and_experiments.md](/Volumes/One%20Touch/NSE/onesec/curvex/docs/essvi_butterfly_backtest/06_validation_and_experiments.md)

## Recommended project structure

Use this as the implementation skeleton for the backtest:

```text
curvex/
  data/
    metadata/
      CONTRACTS_INVENTORY.csv
      MANIFEST.csv
    raw/
      january_2026/
  docs/
    essvi_butterfly_backtest/
  src/
    essvi_bfly/
      config.py
      instruments.py
      io/
        manifest.py
        parquet_loader.py
      preprocess/
        normalize.py
        state_reconstruction.py
        bars.py
        option_chain.py
      iv/
        black_scholes.py
        implied_vol.py
      surface/
        essvi.py
        calibrate.py
        diagnostics.py
      signal/
        residuals.py
        zscores.py
        candidate_selection.py
      portfolio/
        structures.py
        greeks.py
        pnl.py
      execution/
        fills.py
        slippage.py
      backtest/
        engine.py
        event_loop.py
        results.py
  notebooks/
  outputs/
    essvi_bfly/
      intermediate/
      reports/
```

## Milestone sequence

- Milestone 1: Build contract parsing, manifest loading, and state reconstruction.
- Milestone 2: Build 1-minute and 5-minute option-chain snapshots with reconstructed mids.
- Milestone 3: Add implied-vol inversion, eSSVI slice calibration, and residual diagnostics.
- Milestone 4: Add butterfly candidate selection, execution assumptions, and portfolio accounting.
- Milestone 5: Run walk-forward experiments, cost stress tests, and failure analysis.

## Repo-specific assumptions to lock in early

- Use [`data/metadata/CONTRACTS_INVENTORY.csv`](/Volumes/One%20Touch/NSE/onesec/curvex/data/metadata/CONTRACTS_INVENTORY.csv) as the contract master.
- Use [`data/metadata/MANIFEST.csv`](/Volumes/One%20Touch/NSE/onesec/curvex/data/metadata/MANIFEST.csv) to locate daily files.
- Treat `NIFTY50`, `NIFTYBANK`, and `SENSEX` index files as the underlying spot proxies.
- Treat `NIFTY26*FUT` and `BANKNIFTY26*FUT` as optional hedge and forward inputs.
- Sort every file ascending by `ft` and `timestamp` before doing any feature engineering.
