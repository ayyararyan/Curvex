from __future__ import annotations

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig
from essvi_bfly.iv.black_scholes import price_option_forward


def build_straddle_chain(chain: pd.DataFrame, diagnostics: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    diag_ok = diagnostics[diagnostics["converged"] & (diagnostics["rmse"].fillna(np.inf) <= config.calibration_rmse_limit)]
    ok_keys = set(zip(diag_ok["bar_close"], diag_ok["root_symbol"], diag_ok["expiry_code"]))

    base_cols = [
        "bar_close",
        "session_date",
        "root_symbol",
        "expiry_code",
        "strike",
        "underlying_price",
        "forward",
        "tau_years",
        "quote_ok",
        "mid",
        "spread",
        "iv_market",
        "iv_essvi",
        "residual_iv",
        "zscore",
        "lot_size",
        "contract_multiplier",
        "contract_name",
        "open_bp1",
        "open_sp1",
        "open_bq1",
        "open_sq1",
        "bp1",
        "sp1",
        "bq1",
        "sq1",
    ]
    ce = chain[chain["option_side"] == "CE"][base_cols].copy()
    pe = chain[chain["option_side"] == "PE"][base_cols].copy()
    ce = ce.rename(
        columns={
            "contract_name": "call_contract",
            "quote_ok": "call_quote_ok",
            "mid": "call_mid",
            "spread": "call_spread",
            "iv_market": "call_iv_market",
            "iv_essvi": "call_iv_essvi",
            "residual_iv": "call_residual_iv",
            "zscore": "call_zscore",
            "open_bp1": "call_open_bp1",
            "open_sp1": "call_open_sp1",
            "open_bq1": "call_open_bq1",
            "open_sq1": "call_open_sq1",
            "bp1": "call_bp1",
            "sp1": "call_sp1",
            "bq1": "call_bq1",
            "sq1": "call_sq1",
        }
    )
    pe = pe.rename(
        columns={
            "contract_name": "put_contract",
            "quote_ok": "put_quote_ok",
            "mid": "put_mid",
            "spread": "put_spread",
            "iv_market": "put_iv_market",
            "iv_essvi": "put_iv_essvi",
            "residual_iv": "put_residual_iv",
            "zscore": "put_zscore",
            "open_bp1": "put_open_bp1",
            "open_sp1": "put_open_sp1",
            "open_bq1": "put_open_bq1",
            "open_sq1": "put_open_sq1",
            "bp1": "put_bp1",
            "sp1": "put_sp1",
            "bq1": "put_bq1",
            "sq1": "put_sq1",
        }
    )
    merged = ce.merge(
        pe,
        on=["bar_close", "session_date", "root_symbol", "expiry_code", "strike", "underlying_price", "forward", "tau_years", "lot_size", "contract_multiplier"],
        how="inner",
    )
    merged = merged[
        merged.apply(lambda r: (r["bar_close"], r["root_symbol"], r["expiry_code"]) in ok_keys, axis=1)
    ].copy()
    merged["market_premium"] = merged["call_mid"] + merged["put_mid"]
    merged["model_premium"] = [
        price_option_forward(f, k, t, config.risk_free_rate, civ, "CE") + price_option_forward(f, k, t, config.risk_free_rate, piv, "PE")
        if np.isfinite(civ) and np.isfinite(piv) and np.isfinite(f) and np.isfinite(k) and np.isfinite(t)
        else np.nan
        for f, k, t, civ, piv in zip(
            merged["forward"],
            merged["strike"],
            merged["tau_years"],
            merged["call_iv_essvi"],
            merged["put_iv_essvi"],
        )
    ]
    merged["straddle_residual"] = merged["market_premium"] - merged["model_premium"]
    merged["zscore"] = (merged["call_zscore"] + merged["put_zscore"]) / 2.0
    merged["quote_ok"] = merged["call_quote_ok"] & merged["put_quote_ok"]
    merged["sign_consistent"] = np.sign(merged["call_zscore"].fillna(0)) == np.sign(merged["put_zscore"].fillna(0))
    return merged


def select_straddle_candidates(straddle_chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = straddle_chain.copy()
    out = out[
        out["quote_ok"]
        & out["sign_consistent"]
        & np.isfinite(out["zscore"])
        & np.isfinite(out["model_premium"])
    ].copy()
    out["direction"] = np.where(
        out["zscore"] <= -config.entry_z,
        "LONG_STRADDLE",
        np.where(out["zscore"] >= config.entry_z, "SHORT_STRADDLE", None),
    )
    out = out[out["direction"].notna()].copy()
    out["theoretical_edge"] = np.where(
        out["direction"] == "LONG_STRADDLE",
        (out["model_premium"] - out["market_premium"]) * out["lot_size"] * out["contract_multiplier"],
        (out["market_premium"] - out["model_premium"]) * out["lot_size"] * out["contract_multiplier"],
    )
    out["estimated_cost"] = (
        (out["call_spread"].fillna(0) + out["put_spread"].fillna(0)) * out["lot_size"] * out["contract_multiplier"]
        + 2.0 * config.leg_brokerage_per_order
    )
    return out.reset_index(drop=True)
