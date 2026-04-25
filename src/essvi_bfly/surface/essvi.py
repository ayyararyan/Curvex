from __future__ import annotations

import numpy as np


def total_variance_ssvi(k: np.ndarray, theta: float, rho: float, psi: float) -> np.ndarray:
    phi = psi / max(theta, 1e-12)
    return 0.5 * theta * (1.0 + rho * phi * k + np.sqrt((phi * k + rho) ** 2 + 1.0 - rho * rho))


def implied_vol_ssvi(k: np.ndarray, tau: np.ndarray, theta: float, rho: float, psi: float) -> np.ndarray:
    total_var = total_variance_ssvi(k, theta, rho, psi)
    return np.sqrt(np.maximum(total_var / np.maximum(tau, 1e-12), 0.0))
