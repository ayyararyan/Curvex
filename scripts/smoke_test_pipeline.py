#!/usr/bin/env python3
"""Smoke-test pipeline for a single session before a full backtest run.

Runs 11 independent data-quality checks and exits 0 on all pass, 1 on any failure.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig
from essvi_bfly.instruments import load_manifest
from essvi_bfly.preprocess.option_chain import build_session_chain
from essvi_bfly.signal.residuals import calibrate_surface
from essvi_bfly.signal.zscores import add_residual_zscores


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Print PASS/FAIL line with optional detail. Returns True if passed."""
    status = "PASS" if condition else "FAIL"
    suffix = f"  {detail}" if detail else ""
    print(f"{status}: {label}{suffix}")
    return condition


def main() -> None:
    """Run 11 smoke checks for (session, symbol). Exit 0=all pass, 1=any fail."""
    parser = argparse.ArgumentParser(description="Smoke-test pipeline for a single session.")
    parser.add_argument("--session", default="2026_01_02", help="Session date (YYYY_MM_DD)")
    parser.add_argument("--symbol", default="NIFTY", help="Root symbol")
    parser.add_argument("--rmse-limit-override", type=float, default=None, dest="rmse_limit")
    args = parser.parse_args()

    config = BacktestConfig(root_symbols=(args.symbol,))
    manifest = load_manifest(config.manifest_path)

    artifacts = build_session_chain(manifest, args.session, args.symbol, config)
    chain, diagnostics = calibrate_surface(artifacts.option_bars, config)
    chain = add_residual_zscores(chain, config)

    results: list[bool] = []

    # 1. Chain non-empty
    results.append(check("Chain non-empty", len(chain) > 0, f"rows={len(chain)}"))

    # 2. Tau positivity
    bad_tau = int((chain["tau_years"] <= 0).sum()) if "tau_years" in chain.columns else len(chain)
    results.append(check("Tau positivity", bad_tau == 0, f"bad_rows={bad_tau}"))

    # 3. ATM mid prices
    if "forward" in chain.columns and "strike" in chain.columns and "mid" in chain.columns:
        valid_fwd = chain["forward"].notna() & (chain["forward"] > 0) & chain["strike"].notna()
        atm_mask = valid_fwd & (np.log(chain["strike"].where(valid_fwd, 1) / chain["forward"].where(valid_fwd, 1)).abs() <= 0.03)
        atm_rows = chain[atm_mask]
        if len(atm_rows) == 0:
            results.append(check("ATM mid prices > 0", False, "no ATM rows found"))
        else:
            atm_fail = int((atm_rows["mid"].fillna(0) <= 0).sum())
            results.append(check("ATM mid prices > 0", atm_fail == 0, f"atm_rows={len(atm_rows)}, fail={atm_fail}"))
    else:
        results.append(check("ATM mid prices > 0", False, "required columns missing"))

    # 4. Forward quality
    if "forward" in chain.columns and "underlying_price" in chain.columns and len(chain) > 0:
        fwd_null = int(chain["forward"].isna().sum())
        if fwd_null == 0:
            valid_rows = chain["underlying_price"].notna() & (chain["underlying_price"] > 0) & chain["forward"].notna()
            if valid_rows.any():
                deviations = (chain.loc[valid_rows, "forward"] / chain.loc[valid_rows, "underlying_price"] - 1).abs()
                max_dev = float(deviations.max())
            else:
                max_dev = float("nan")
            fwd_ok = max_dev <= 0.01
        else:
            fwd_ok = False
            max_dev = float("nan")
        results.append(check("Forward quality", fwd_ok, f"null={fwd_null}, max_dev={max_dev:.4f}"))
    else:
        results.append(check("Forward quality", False, "required columns missing"))

    # 5. Quote coverage
    if "quote_ok" in chain.columns and len(chain) > 0:
        pct = float(chain["quote_ok"].mean() * 100)
        results.append(check("Quote coverage >= 50%", pct >= 50, f"pct={pct:.1f}%"))
    else:
        results.append(check("Quote coverage >= 50%", False, "quote_ok column missing or empty chain"))

    # 6. Calibration convergence
    if len(diagnostics) > 0 and "converged" in diagnostics.columns:
        if args.rmse_limit is not None and "rmse" in diagnostics.columns:
            diag_filtered = diagnostics[diagnostics["rmse"] <= args.rmse_limit]
        else:
            diag_filtered = diagnostics
        converged_count = int(diag_filtered["converged"].sum())
        total = len(diag_filtered)
    else:
        converged_count = 0
        total = 0
    results.append(check("Calibration convergence >= 3", converged_count >= 3, f"converged={converged_count}/{total}"))

    # 7. Bar count >= 60 per contract
    if "contract_name" in chain.columns and "bar_close" in chain.columns and len(chain) > 0:
        contract_counts = chain.groupby("contract_name")["bar_close"].nunique()
        min_bars_contract = str(contract_counts.idxmin())
        min_bars = int(contract_counts.min())
        bar_ok = min_bars >= 60
        results.append(check("Bar count >= 60 per contract", bar_ok, f"min={min_bars} ({min_bars_contract})"))
    else:
        results.append(check("Bar count >= 60 per contract", False, "required columns missing or empty chain"))

    # 8. Strike coverage >= 5 per expiry within ATM ±5%
    if all(c in chain.columns for c in ("strike", "forward", "expiry_code")) and len(chain) > 0:
        nna = chain[chain["forward"].notna() & chain["strike"].notna() & (chain["forward"] > 0)]
        if len(nna) > 0:
            lm = np.log(nna["strike"] / nna["forward"])
            atm5 = nna[lm.abs() <= 0.05]
            if len(atm5) > 0:
                strike_counts = atm5.groupby("expiry_code")["strike"].nunique()
                min_exp = str(strike_counts.idxmin())
                min_strikes = int(strike_counts.min())
                strike_ok = min_strikes >= 5
            else:
                min_exp, min_strikes, strike_ok = "N/A", 0, False
        else:
            min_exp, min_strikes, strike_ok = "N/A", 0, False
        results.append(check("Strike coverage >= 5 per expiry", strike_ok, f"min={min_strikes} ({min_exp})"))
    else:
        results.append(check("Strike coverage >= 5 per expiry", False, "required columns missing or empty chain"))

    # 9. No duplicate (bar_close, contract_name) pairs
    if "bar_close" in chain.columns and "contract_name" in chain.columns:
        dup_count = int(chain.duplicated(subset=["bar_close", "contract_name"]).sum())
        results.append(check("No duplicate (bar_close, contract_name)", dup_count == 0, f"dups={dup_count}"))
    else:
        results.append(check("No duplicate (bar_close, contract_name)", False, "required columns missing"))

    # 10. Underlying contract resolved
    underlying_contract = config.underlying_spot_map.get(args.symbol)
    if underlying_contract:
        manifest_match = manifest[
            (manifest["session_date"] == args.session) & (manifest["contract_name"] == underlying_contract)
        ]
        underlying_ok = len(manifest_match) > 0
    else:
        underlying_ok = False
    results.append(check("Underlying contract resolved", underlying_ok, f"contract={underlying_contract}"))

    # 11. Session-boundary z-score NaN guard
    window = config.zscore_window
    if "zscore" in chain.columns and "contract_name" in chain.columns and "bar_close" in chain.columns:
        first_n = (
            chain.sort_values(["contract_name", "bar_close"])
                 .groupby("contract_name")
                 .head(window)
        )
        non_nan = int(first_n["zscore"].notna().sum())
        results.append(check(f"Z-score NaN in first {window} bars per contract", non_nan == 0, f"non_nan={non_nan}"))
    else:
        results.append(check(f"Z-score NaN in first {window} bars per contract", False, "zscore column missing"))

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
