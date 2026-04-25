from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from essvi_bfly.surface.essvi import implied_vol_ssvi, total_variance_ssvi

THETA_FLOOR_FRAC = 0.25
THETA_CEIL_MULT = 16.0
PHI_CAP = 500.0
CONVEXITY_GRID = np.linspace(-0.05, 0.05, 21)


@dataclass(slots=True)
class CalibrationResult:
    theta: float | None
    rho: float | None
    psi: float | None
    rmse: float | None
    converged: bool
    strike_count: int


def _psi_upper(theta: float, rho: float) -> float:
    rho_abs = abs(rho)
    cap_one = 4.0 / (1.0 + rho_abs)
    cap_two = 2.0 * np.sqrt(max(theta, 1e-12) / (1.0 + rho_abs))
    return min(cap_one, cap_two, PHI_CAP * theta) * 0.999


def _butterfly_constraints_ok(theta: float, rho: float, psi: float) -> bool:
    rho_abs = abs(rho)
    lhs_one = psi * (1.0 + rho_abs)
    lhs_two = psi * psi * (1.0 + rho_abs)
    return bool(lhs_one <= 4.0 + 1e-12 and lhs_two <= 4.0 * theta + 1e-12)


def _map_params(raw: np.ndarray, theta_floor: float, theta_ceil: float) -> tuple[float, float, float]:
    theta = theta_floor + (theta_ceil - theta_floor) / (1.0 + np.exp(-raw[0]))
    rho = np.tanh(raw[1])
    psi_lower = 1e-4 * theta
    psi_upper = max(_psi_upper(theta, rho), psi_lower * 1.01)
    psi = psi_lower + (psi_upper - psi_lower) / (1.0 + np.exp(-raw[2]))
    return theta, rho, psi


def _total_variance_convex(theta: float, rho: float, psi: float, tau: float) -> bool:
    if not _butterfly_constraints_ok(theta, rho, psi):
        return False
    if tau <= 0:
        return False
    iv = implied_vol_ssvi(CONVEXITY_GRID, np.full_like(CONVEXITY_GRID, tau), theta, rho, psi)
    if not np.all(np.isfinite(iv)):
        return False
    total_var = iv**2 * tau
    second_diff = total_var[2:] - 2.0 * total_var[1:-1] + total_var[:-2]
    return bool(np.all(second_diff >= -1e-10))


def calibrate_slice(slice_df: pd.DataFrame, warm_start: tuple[float, float, float] | None = None) -> CalibrationResult:
    slice_df = slice_df.dropna(subset=["k", "tau_years", "iv_market", "weight"]).copy()
    if len(slice_df) < 3:
        return CalibrationResult(None, None, None, None, False, len(slice_df))
    target = (slice_df["iv_market"].to_numpy() ** 2) * slice_df["tau_years"].to_numpy()
    k = slice_df["k"].to_numpy()
    weight = slice_df["weight"].to_numpy()
    tau_median = float(np.nanmedian(slice_df["tau_years"].to_numpy()))

    target_median = float(np.nanmedian(target.clip(1e-8)))
    theta_floor = max(THETA_FLOOR_FRAC * target_median, 1e-8)
    theta_ceil = max(THETA_CEIL_MULT * target_median, theta_floor * 4.0)

    def invert(theta: float, rho: float, psi: float) -> np.ndarray:
        theta_c = np.clip(theta, theta_floor, theta_ceil)
        t = (theta_c - theta_floor) / max(theta_ceil - theta_floor, 1e-12)
        t = np.clip(t, 1e-6, 1 - 1e-6)
        raw0 = np.log(t / (1 - t))
        raw1 = np.arctanh(np.clip(rho, -0.999, 0.999))
        psi_lower = 1e-4 * theta_c
        psi_upper = max(_psi_upper(theta_c, rho), psi_lower * 1.01)
        s = (psi - psi_lower) / max(psi_upper - psi_lower, 1e-12)
        s = np.clip(s, 1e-6, 1 - 1e-6)
        raw2 = np.log(s / (1 - s))
        return np.array([raw0, raw1, raw2], dtype=float)

    if warm_start is None:
        init = invert(target_median, 0.0, 0.05 * target_median)
    else:
        init = invert(*warm_start)

    def objective(raw: np.ndarray) -> np.ndarray:
        theta, rho, psi = _map_params(raw, theta_floor, theta_ceil)
        model = total_variance_ssvi(k, theta, rho, psi)
        return np.sqrt(weight) * (model - target)

    result = least_squares(objective, init, max_nfev=200)
    theta, rho, psi = _map_params(result.x, theta_floor, theta_ceil)
    model_iv = implied_vol_ssvi(k, slice_df["tau_years"].to_numpy(), theta, rho, psi)
    rmse = float(np.sqrt(np.mean((model_iv - slice_df["iv_market"].to_numpy()) ** 2)))
    converged = bool(result.success) and _total_variance_convex(theta, rho, psi, tau_median)
    return CalibrationResult(theta, rho, psi, rmse, converged, len(slice_df))


def evaluate_slice(slice_df: pd.DataFrame, calibration: CalibrationResult) -> pd.DataFrame:
    out = slice_df.copy()
    if not calibration.converged:
        out["iv_essvi"] = np.nan
    else:
        out["iv_essvi"] = implied_vol_ssvi(
            out["k"].to_numpy(),
            out["tau_years"].to_numpy(),
            calibration.theta,
            calibration.rho,
            calibration.psi,
        )
    out["residual_iv"] = out["iv_market"] - out["iv_essvi"]
    return out
