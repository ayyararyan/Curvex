from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq, newton

from essvi_bfly.iv.black_scholes import price_option_forward


@dataclass(slots=True)
class IVResult:
    iv: float | None
    status: str
    iterations: int


def implied_volatility(price: float, forward: float, strike: float, tau: float, rate: float, option_side: str) -> IVResult:
    disc = np.exp(-rate * max(float(tau), 0.0))
    lower_bound = disc * max(forward - strike, 0.0) if option_side == "CE" else disc * max(strike - forward, 0.0)
    upper_bound = disc * forward if option_side == "CE" else disc * strike
    if any(np.isnan([price, forward, strike, tau])) or tau <= 0 or forward <= 0 or strike <= 0:
        return IVResult(None, "invalid_input", 0)
    tol = max(1e-8, 1e-6 * upper_bound)
    if price < lower_bound - tol or price > upper_bound + tol:
        return IVResult(None, "invalid_price_bounds", 0)

    def objective(vol: float) -> float:
        return price_option_forward(forward, strike, tau, rate, vol, option_side) - price

    try:
        root = newton(objective, x0=0.2, maxiter=20)
        if np.isfinite(root) and 0 < root <= 5.0:
            return IVResult(float(root), "newton", 20)
    except Exception:
        pass
    try:
        root = brentq(objective, 1e-4, 5.0, maxiter=100)
        return IVResult(float(root), "brentq", 100)
    except Exception:
        return IVResult(None, "failed", 100)
