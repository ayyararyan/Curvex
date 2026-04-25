from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig
from essvi_bfly.iv.black_scholes import price_option_forward


@dataclass(slots=True)
class ButterflyCandidate:
    bar_close: pd.Timestamp
    root_symbol: str
    expiry_code: str
    option_side: str
    body_contract: str
    wing_low_contract: str
    wing_high_contract: str
    direction: str
    zscore: float
    market_premium: float
    model_premium: float
    theoretical_edge: float
    estimated_cost: float


def _structure_value(low: pd.Series, body: pd.Series, high: pd.Series, price_col: str) -> float:
    return float(low[price_col] - 2.0 * body[price_col] + high[price_col])


def select_candidates(
    chain: pd.DataFrame,
    diagnostics: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    # Direction mapping (audit-verified): z < 0 → SHORT_BFLY (buy underpriced body,
    # sell wings); z >= 0 → LONG_BFLY (sell overpriced body, buy wings). Consistent
    # with engine.py._build_actions: LONG_BFLY entry = BUY wing_low + SELL body × 2
    # + BUY wing_high (standard industry convention). z = 0 never reaches this branch
    # in practice — filtered upstream by `abs(z) < entry_z` before direction is assigned.
    diag_ok = diagnostics[diagnostics["converged"] & (diagnostics["rmse"].fillna(np.inf) <= config.calibration_rmse_limit)]
    ok_keys = set(zip(diag_ok["bar_close"], diag_ok["root_symbol"], diag_ok["expiry_code"]))
    rows: list[dict] = []
    grouped = chain.groupby(["bar_close", "root_symbol", "expiry_code", "option_side"], sort=True)
    for (bar_close, root_symbol, expiry_code, option_side), grp in grouped:
        if (bar_close, root_symbol, expiry_code) not in ok_keys:
            continue
        grp = grp.copy().sort_values("strike")
        for i in range(1, len(grp) - 1):
            low = grp.iloc[i - 1]
            body = grp.iloc[i]
            high = grp.iloc[i + 1]
            if not (np.isfinite(low["strike"]) and np.isfinite(body["strike"]) and np.isfinite(high["strike"])):
                continue
            if (body["strike"] - low["strike"]) != (high["strike"] - body["strike"]):
                continue
            if not bool(low["quote_ok"] and body["quote_ok"] and high["quote_ok"]):
                continue
            if body["same_sign_persistence"] < config.persistence_bars or not np.isfinite(body["zscore"]):
                continue
            if abs(body["zscore"]) < config.entry_z:
                continue
            if config.enforce_otm_structure_side:
                forward = grp["forward"].median()
                if option_side == "CE" and body["strike"] < forward:
                    continue
                if option_side == "PE" and body["strike"] > forward:
                    continue
            market_premium = _structure_value(low, body, high, "mid")
            if not np.isfinite(low["iv_essvi"]) or not np.isfinite(body["iv_essvi"]) or not np.isfinite(high["iv_essvi"]):
                continue
            low_model = price_option_forward(low["forward"], low["strike"], low["tau_years"], config.risk_free_rate, low["iv_essvi"], option_side)
            body_model = price_option_forward(body["forward"], body["strike"], body["tau_years"], config.risk_free_rate, body["iv_essvi"], option_side)
            high_model = price_option_forward(high["forward"], high["strike"], high["tau_years"], config.risk_free_rate, high["iv_essvi"], option_side)
            model_premium = low_model - 2.0 * body_model + high_model
            if body["zscore"] < 0:
                direction = "SHORT_BFLY"
                edge = market_premium - model_premium
            else:
                direction = "LONG_BFLY"
                edge = model_premium - market_premium
            estimated_cost = (
                low["spread"] + 2.0 * body["spread"] + high["spread"]
            ) / 2.0
            lot_size = float(body.get("lot_size", 1.0) or 1.0)
            contract_multiplier = float(body.get("contract_multiplier", 1.0) or 1.0)
            gross_edge_lot = edge * lot_size * contract_multiplier
            estimated_cost = estimated_cost * lot_size * contract_multiplier + 4.0 * config.leg_brokerage_per_order
            if config.require_positive_edge and gross_edge_lot <= 0:
                continue
            if gross_edge_lot <= estimated_cost:
                continue
            if gross_edge_lot / max(estimated_cost, 1e-9) < config.min_edge_to_cost_ratio:
                continue
            rows.append(
                {
                    "bar_close": bar_close,
                    "root_symbol": root_symbol,
                    "expiry_code": expiry_code,
                    "option_side": option_side,
                    "body_contract": body["contract_name"],
                    "wing_low_contract": low["contract_name"],
                    "wing_high_contract": high["contract_name"],
                    "direction": direction,
                    "zscore": body["zscore"],
                    "market_premium": market_premium,
                    "model_premium": model_premium,
                    "theoretical_edge": gross_edge_lot,
                    "estimated_cost": estimated_cost,
                    "lot_size": lot_size,
                    "contract_multiplier": contract_multiplier,
                }
            )
    return pd.DataFrame(rows)
