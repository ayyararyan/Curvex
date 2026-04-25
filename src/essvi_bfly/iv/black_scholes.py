from __future__ import annotations

import math

from scipy.stats import norm


def _d1_d2(spot: float, strike: float, tau: float, rate: float, vol: float) -> tuple[float, float]:
    safe_spot = max(float(spot), 1e-12)
    safe_strike = max(float(strike), 1e-12)
    safe_tau = max(float(tau), 1e-12)
    safe_vol = min(max(float(vol), 1e-8), 5.0)
    sqrt_tau = math.sqrt(safe_tau)
    numer = math.log(safe_spot / safe_strike) + (rate + 0.5 * safe_vol * safe_vol) * safe_tau
    denom = safe_vol * sqrt_tau
    d1 = numer / denom
    d2 = d1 - safe_vol * sqrt_tau
    return d1, d2


def _d1_d2_forward(forward: float, strike: float, tau: float, vol: float) -> tuple[float, float]:
    safe_forward = max(float(forward), 1e-12)
    safe_strike = max(float(strike), 1e-12)
    safe_tau = max(float(tau), 1e-12)
    safe_vol = min(max(float(vol), 1e-8), 5.0)
    sqrt_tau = math.sqrt(safe_tau)
    numer = math.log(safe_forward / safe_strike) + 0.5 * safe_vol * safe_vol * safe_tau
    denom = safe_vol * sqrt_tau
    d1 = numer / denom
    d2 = d1 - safe_vol * sqrt_tau
    return d1, d2


def price_option(spot: float, strike: float, tau: float, rate: float, vol: float, option_side: str) -> float:
    if tau <= 0:
        intrinsic = max(spot - strike, 0.0) if option_side == "CE" else max(strike - spot, 0.0)
        return intrinsic
    d1, d2 = _d1_d2(spot, strike, tau, rate, vol)
    disc = math.exp(-rate * max(float(tau), 0.0))
    if option_side == "CE":
        return spot * norm.cdf(d1) - strike * disc * norm.cdf(d2)
    return strike * disc * norm.cdf(-d2) - spot * norm.cdf(-d1)


def price_option_forward(forward: float, strike: float, tau: float, rate: float, vol: float, option_side: str) -> float:
    disc = math.exp(-rate * max(float(tau), 0.0))
    if tau <= 0:
        intrinsic = max(forward - strike, 0.0) if option_side == "CE" else max(strike - forward, 0.0)
        return disc * intrinsic
    d1, d2 = _d1_d2_forward(forward, strike, tau, vol)
    if option_side == "CE":
        return disc * (forward * norm.cdf(d1) - strike * norm.cdf(d2))
    return disc * (strike * norm.cdf(-d2) - forward * norm.cdf(-d1))


def delta(spot: float, strike: float, tau: float, rate: float, vol: float, option_side: str) -> float:
    d1, _ = _d1_d2(spot, strike, tau, rate, vol)
    return norm.cdf(d1) if option_side == "CE" else norm.cdf(d1) - 1.0


def gamma(spot: float, strike: float, tau: float, rate: float, vol: float) -> float:
    d1, _ = _d1_d2(spot, strike, tau, rate, vol)
    return norm.pdf(d1) / (spot * vol * math.sqrt(tau))


def vega(spot: float, strike: float, tau: float, rate: float, vol: float) -> float:
    d1, _ = _d1_d2(spot, strike, tau, rate, vol)
    return spot * norm.pdf(d1) * math.sqrt(tau)


def theta(spot: float, strike: float, tau: float, rate: float, vol: float, option_side: str) -> float:
    d1, d2 = _d1_d2(spot, strike, tau, rate, vol)
    first = -(spot * norm.pdf(d1) * vol) / (2 * math.sqrt(tau))
    disc = math.exp(-rate * tau)
    if option_side == "CE":
        second = -rate * strike * disc * norm.cdf(d2)
    else:
        second = rate * strike * disc * norm.cdf(-d2)
    return first + second
