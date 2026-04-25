import types
import unittest.mock

import numpy as np
import pandas as pd

from essvi_bfly.backtest.engine import BacktestEngine
from essvi_bfly.config import BacktestConfig
from essvi_bfly.iv.black_scholes import price_option_forward
from essvi_bfly.signal.candidate_selection import select_candidates
from essvi_bfly.signal.zscores import add_residual_zscores, persistence


def make_butterfly_chain(
    body_zscore: float,
    body_iv_market: float,
    body_iv_essvi: float,
    body_persistence: int = 3,
    lot_size: float = 1.0,
    contract_multiplier: float = 1.0,
) -> tuple:
    config = BacktestConfig(
        enforce_otm_structure_side=False,
        require_positive_edge=True,
        entry_z=1.5,
        persistence_bars_5m=2,
        bar_freq="5min",
        leg_brokerage_per_order=0.0,
        min_edge_to_cost_ratio=0.0,
        fee_rate=0.0,
        tax_rate=0.0,
    )
    bar_close = pd.Timestamp("2024-01-01 10:00")
    forward = 18000.0
    tau = 0.1
    rate = config.risk_free_rate
    option_side = "CE"
    wing_iv = 0.20
    # mid prices computed at iv_market so market_premium is BS-consistent
    low_mid = price_option_forward(forward, 17900.0, tau, rate, wing_iv, option_side)
    body_mid = price_option_forward(forward, 18000.0, tau, rate, body_iv_market, option_side)
    high_mid = price_option_forward(forward, 18100.0, tau, rate, wing_iv, option_side)
    chain = pd.DataFrame([
        {
            "contract_name": "C_LOW", "session_date": "2024-01-01", "bar_close": bar_close,
            "root_symbol": "NIFTY", "expiry_code": "26JAN", "option_side": option_side,
            "strike": 17900.0, "forward": forward, "tau_years": tau, "mid": low_mid,
            "quote_ok": True, "iv_market": wing_iv, "iv_essvi": wing_iv,
            "residual_iv": 0.0, "zscore": 0.0, "same_sign_persistence": 0,
            "spread": 0.01, "lot_size": lot_size, "contract_multiplier": contract_multiplier,
        },
        {
            "contract_name": "C_BODY", "session_date": "2024-01-01", "bar_close": bar_close,
            "root_symbol": "NIFTY", "expiry_code": "26JAN", "option_side": option_side,
            "strike": 18000.0, "forward": forward, "tau_years": tau, "mid": body_mid,
            "quote_ok": True, "iv_market": body_iv_market, "iv_essvi": body_iv_essvi,
            "residual_iv": body_iv_market - body_iv_essvi, "zscore": body_zscore,
            "same_sign_persistence": body_persistence,
            "spread": 0.01, "lot_size": lot_size, "contract_multiplier": contract_multiplier,
        },
        {
            "contract_name": "C_HIGH", "session_date": "2024-01-01", "bar_close": bar_close,
            "root_symbol": "NIFTY", "expiry_code": "26JAN", "option_side": option_side,
            "strike": 18100.0, "forward": forward, "tau_years": tau, "mid": high_mid,
            "quote_ok": True, "iv_market": wing_iv, "iv_essvi": wing_iv,
            "residual_iv": 0.0, "zscore": 0.0, "same_sign_persistence": 0,
            "spread": 0.01, "lot_size": lot_size, "contract_multiplier": contract_multiplier,
        },
    ])
    diagnostics = pd.DataFrame([{
        "bar_close": bar_close, "root_symbol": "NIFTY", "expiry_code": "26JAN",
        "converged": True, "rmse": 0.001,
    }])
    return chain, diagnostics, config


def test_build_actions_long_bfly_convention():
    candidate = types.SimpleNamespace(
        direction="LONG_BFLY",
        wing_low_contract="C_LOW",
        body_contract="C_BODY",
        wing_high_contract="C_HIGH",
    )
    low = object()
    body = object()
    high = object()
    engine = unittest.mock.MagicMock(spec=BacktestEngine)
    actions = BacktestEngine._build_actions(engine, candidate, (low, body, high), is_exit=False)
    assert [(a, c) for a, c, _ in actions] == [
        ("BUY", "C_LOW"),
        ("SELL", "C_BODY"),
        ("SELL", "C_BODY"),
        ("BUY", "C_HIGH"),
    ]


def test_persistence_counter_sign_flip():
    series = pd.Series([1.2, 1.5, -1.3, -1.8, -2.0, float("nan")])
    result = persistence(series)
    assert list(result) == [1, 2, 1, 2, 3, 0]


def test_persistence_counter_leading_nan():
    series = pd.Series([float("nan"), float("nan"), 1.5, 1.8, float("nan"), 2.0])
    result = persistence(series)
    assert list(result) == [0, 0, 1, 2, 0, 1]


def test_zscore_rolling_within_session():
    n_per_session = 30

    def make_session(date_str, start_time):
        times = pd.date_range(start_time, periods=n_per_session, freq="5min")
        return pd.DataFrame({
            "contract_name": "TEST_CONTRACT",
            "session_date": date_str,
            "bar_close": times,
            "residual_iv": np.linspace(0.01, 0.10, n_per_session),
        })

    chain = pd.concat(
        [make_session("2024-01-01", "2024-01-01 09:15"),
         make_session("2024-01-02", "2024-01-02 09:15")],
        ignore_index=True,
    )
    # window=10 → min_periods=min(20,10)=10 → bars 0-8 NaN, bar 9+ finite
    config = BacktestConfig(zscore_window_5m=10, bar_freq="5min")
    result = add_residual_zscores(chain, config)

    sess1 = result[result["session_date"] == "2024-01-01"].sort_values("bar_close").reset_index(drop=True)
    sess2 = result[result["session_date"] == "2024-01-02"].sort_values("bar_close").reset_index(drop=True)

    assert sess1.loc[:8, "zscore"].isna().all(), "Session 1 bars 0-8 should be NaN"
    assert sess1.loc[9:, "zscore"].notna().all(), "Session 1 bar 9+ should be finite"
    # KEY REGRESSION GUARD: fails before section-02 fix
    assert sess2.loc[:8, "zscore"].isna().all(), "Session 2 bars 0-8 should be NaN (boundary must reset)"
    assert sess2.loc[9:, "zscore"].notna().all(), "Session 2 bar 9+ should be finite"
    assert result["same_sign_persistence"].isna().sum() == 0, "same_sign_persistence must have no NaN"


def test_direction_long_bfly():
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=+2.0, body_iv_market=0.25, body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    assert len(candidates) >= 1
    assert (candidates["direction"] == "LONG_BFLY").all()


def test_direction_short_bfly():
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=-2.0, body_iv_market=0.15, body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    assert len(candidates) >= 1
    assert (candidates["direction"] == "SHORT_BFLY").all()


def test_edge_long_bfly_positive():
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=+2.0, body_iv_market=0.25, body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    long_bfly = candidates[candidates["direction"] == "LONG_BFLY"]
    assert len(long_bfly) >= 1
    assert (long_bfly["theoretical_edge"] > 0).all()


def test_edge_short_bfly_positive():
    chain, diagnostics, config = make_butterfly_chain(
        body_zscore=-2.0, body_iv_market=0.15, body_iv_essvi=0.20,
    )
    candidates = select_candidates(chain, diagnostics, config)
    short_bfly = candidates[candidates["direction"] == "SHORT_BFLY"]
    assert len(short_bfly) >= 1
    assert (short_bfly["theoretical_edge"] > 0).all()
