from __future__ import annotations

import pandas as pd

from essvi_bfly.surface.calibrate import CalibrationResult


def calibration_to_row(bar_close: pd.Timestamp, root_symbol: str, expiry_code: str, result: CalibrationResult) -> dict:
    return {
        "bar_close": bar_close,
        "root_symbol": root_symbol,
        "expiry_code": expiry_code,
        "theta": result.theta,
        "rho": result.rho,
        "psi": result.psi,
        "rmse": result.rmse,
        "converged": result.converged,
        "strike_count": result.strike_count,
    }
