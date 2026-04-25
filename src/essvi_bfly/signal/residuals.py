from __future__ import annotations

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig
from essvi_bfly.iv.implied_vol import implied_volatility
from essvi_bfly.surface.calibrate import calibrate_slice, evaluate_slice
from essvi_bfly.surface.diagnostics import calibration_to_row


def _iv_input_mask(chain: pd.DataFrame, config: BacktestConfig) -> pd.Series:
    return (
        chain["quote_ok"].fillna(False)
        & chain["tau_years"].fillna(0).gt(0)
        & chain["mid"].fillna(0).gt(0)
        & chain["mid"].fillna(0).ge(config.min_option_premium)
        & chain["spread"].fillna(np.inf).gt(0)
        & chain["spread_pct"].fillna(np.inf).le(config.max_spread_pct)
        & chain["quote_age_seconds"].fillna(np.inf).le(config.max_quote_age_seconds)
        & chain["bq1"].fillna(0).ge(config.min_quote_size)
        & chain["sq1"].fillna(0).ge(config.min_quote_size)
    )


def _otm_mask(chain: pd.DataFrame) -> pd.Series:
    is_call = chain["option_side"].eq("CE")
    is_put = chain["option_side"].eq("PE")
    return (is_call & chain["strike"].ge(chain["forward"])) | (is_put & chain["strike"].le(chain["forward"]))


def add_market_iv(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = chain.copy()
    ivs: list[float | None] = []
    statuses: list[str] = []
    iterations: list[int] = []
    for row in out.itertuples(index=False):
        if not getattr(row, "iv_input_ok", False) or row.tau_years is None or row.tau_years <= 0:
            ivs.append(np.nan)
            statuses.append("quote_rejected")
            iterations.append(0)
            continue
        result = implied_volatility(row.mid, row.forward, row.strike, row.tau_years, config.risk_free_rate, row.option_side)
        ivs.append(np.nan if result.iv is None else result.iv)
        statuses.append(result.status)
        iterations.append(result.iterations)
    out["iv_market"] = ivs
    out["iv_solver_status"] = statuses
    out["iv_solver_iterations"] = iterations
    return out


def calibrate_surface(chain: pd.DataFrame, config: BacktestConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = chain.copy()
    fallback_forward = chain["underlying_price"] * np.exp((config.risk_free_rate - config.carry_rate) * chain["tau_years"].clip(lower=0))
    chain["forward"] = chain.get("forward", fallback_forward)
    chain["forward"] = chain["forward"].where(chain["forward"].fillna(0).gt(0), fallback_forward)
    chain["iv_input_ok"] = _iv_input_mask(chain, config) & chain["forward"].fillna(0).gt(0)
    chain = add_market_iv(chain, config)
    chain["k"] = np.log(chain["strike"] / chain["forward"])
    chain["surface_eligible"] = chain["iv_input_ok"] & _otm_mask(chain)
    chain["atm_weight"] = np.exp(-(chain["k"] ** 2) / max(config.atm_weight_width, 1e-6))
    chain["weight"] = chain["atm_weight"] / chain["spread"].replace(0, np.nan).abs().fillna(chain["mid"].abs()).replace(0, np.nan)
    chain["weight"] = chain["weight"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    enriched_frames: list[pd.DataFrame] = []
    diag_rows: list[dict] = []
    warm_by_expiry: dict[str, tuple[float, float, float]] = {}
    for (bar_close, root_symbol, expiry_code), slice_df in chain.groupby(["bar_close", "root_symbol", "expiry_code"], sort=True):
        eligible = slice_df[
            slice_df["surface_eligible"]
            & slice_df["iv_market"].notna()
            & (slice_df["tau_years"] > 0)
        ].copy()
        if len(eligible) < config.min_slice_strikes:
            eligible["iv_essvi"] = np.nan
            eligible["residual_iv"] = np.nan
            result = calibrate_slice(pd.DataFrame(columns=["k", "tau_years", "iv_market", "weight"]))
        else:
            warm = warm_by_expiry.get(expiry_code) if config.warm_start else None
            result = calibrate_slice(eligible, warm)
            if result.converged and result.theta is not None:
                warm_by_expiry[expiry_code] = (result.theta, result.rho, result.psi)
            eligible = evaluate_slice(eligible, result)
        slice_out = slice_df.merge(
            eligible[["contract_name", "iv_essvi", "residual_iv"]],
            on="contract_name",
            how="left",
        )
        diag_rows.append(calibration_to_row(bar_close, root_symbol, expiry_code, result))
        enriched_frames.append(slice_out)
    enriched = pd.concat(enriched_frames, ignore_index=True) if enriched_frames else chain
    diagnostics = pd.DataFrame(diag_rows)
    return enriched, diagnostics
