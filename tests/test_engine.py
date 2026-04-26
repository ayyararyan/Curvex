import logging
import types
import unittest.mock

import numpy as np
import pandas as pd
import pytest

from essvi_bfly.backtest.engine import BacktestEngine
from essvi_bfly.config import BacktestConfig
from essvi_bfly.execution.fills import FillResult
from essvi_bfly.preprocess.option_chain import SessionChainArtifacts


def _engine():
    return object.__new__(BacktestEngine)


def _candidate(direction: str):
    return types.SimpleNamespace(
        direction=direction,
        wing_low_contract="LOW",
        body_contract="BODY",
        wing_high_contract="HIGH",
    )


_LOW = pd.Series()
_BODY = pd.Series()
_HIGH = pd.Series()
_QUOTES = (_LOW, _BODY, _HIGH)


# ── _build_actions ────────────────────────────────────────────────────────────


def test_build_actions_long_bfly_entry():
    actions = _engine()._build_actions(_candidate("LONG_BFLY"), _QUOTES, is_exit=False)
    assert len(actions) == 4
    assert (actions[0][0], actions[0][1]) == ("BUY", "LOW")
    assert (actions[1][0], actions[1][1]) == ("SELL", "BODY")
    assert (actions[2][0], actions[2][1]) == ("SELL", "BODY")
    assert (actions[3][0], actions[3][1]) == ("BUY", "HIGH")


def test_build_actions_long_bfly_exit():
    actions = _engine()._build_actions(_candidate("LONG_BFLY"), _QUOTES, is_exit=True)
    assert len(actions) == 4
    assert (actions[0][0], actions[0][1]) == ("SELL", "LOW")
    assert (actions[1][0], actions[1][1]) == ("BUY", "BODY")
    assert (actions[2][0], actions[2][1]) == ("BUY", "BODY")
    assert (actions[3][0], actions[3][1]) == ("SELL", "HIGH")


def test_build_actions_short_bfly_entry():
    actions = _engine()._build_actions(_candidate("SHORT_BFLY"), _QUOTES, is_exit=False)
    assert len(actions) == 4
    assert (actions[0][0], actions[0][1]) == ("SELL", "LOW")
    assert (actions[1][0], actions[1][1]) == ("BUY", "BODY")
    assert (actions[2][0], actions[2][1]) == ("BUY", "BODY")
    assert (actions[3][0], actions[3][1]) == ("SELL", "HIGH")


def test_build_actions_short_bfly_exit():
    actions = _engine()._build_actions(_candidate("SHORT_BFLY"), _QUOTES, is_exit=True)
    assert len(actions) == 4
    assert (actions[0][0], actions[0][1]) == ("BUY", "LOW")
    assert (actions[1][0], actions[1][1]) == ("SELL", "BODY")
    assert (actions[2][0], actions[2][1]) == ("SELL", "BODY")
    assert (actions[3][0], actions[3][1]) == ("BUY", "HIGH")


@pytest.mark.parametrize("direction,is_exit", [
    ("LONG_BFLY", False),
    ("LONG_BFLY", True),
    ("SHORT_BFLY", False),
    ("SHORT_BFLY", True),
])
def test_build_actions_body_appears_twice(direction, is_exit):
    actions = _engine()._build_actions(_candidate(direction), _QUOTES, is_exit=is_exit)
    assert len([a for a in actions if a[1] == "BODY"]) == 2


def test_build_actions_contract_names_match_candidate():
    cand = types.SimpleNamespace(
        direction="LONG_BFLY",
        wing_low_contract="WING_A",
        body_contract="CENTER",
        wing_high_contract="WING_Z",
    )
    actions = _engine()._build_actions(cand, _QUOTES, is_exit=False)
    names = [a[1] for a in actions]
    assert names[0] == "WING_A"
    assert names[1] == "CENTER"
    assert names[2] == "CENTER"
    assert names[3] == "WING_Z"


# ── _cashflow_from_fills ──────────────────────────────────────────────────────

# Actions are constructed inline as plain tuples to isolate _cashflow_from_fills
# from _build_actions. Convention: (action, contract_name, quote_row).

_LONG_BFLY_ENTRY = [
    ("BUY",  "LOW",  pd.Series()),
    ("SELL", "BODY", pd.Series()),
    ("SELL", "BODY", pd.Series()),
    ("BUY",  "HIGH", pd.Series()),
]

_LONG_BFLY_EXIT = [
    ("SELL", "LOW",  pd.Series()),
    ("BUY",  "BODY", pd.Series()),
    ("BUY",  "BODY", pd.Series()),
    ("SELL", "HIGH", pd.Series()),
]


def test_cashflow_long_bfly_entry_hand_computed():
    # LOW  BUY  50 → -50
    # BODY SELL 80 → +80
    # BODY SELL 80 → +80
    # HIGH BUY  50 → -50
    # expected = +60
    fills = [
        FillResult(price=50.0, filled=True, reason="ask_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=50.0, filled=True, reason="ask_fill"),
    ]
    result = _engine()._cashflow_from_fills(_LONG_BFLY_ENTRY, fills, lot_size=1.0, contract_multiplier=1.0)
    assert result == pytest.approx(60.0)


def test_cashflow_long_bfly_exit_hand_computed():
    # LOW  SELL 45 → +45
    # BODY BUY  65 → -65
    # BODY BUY  65 → -65
    # HIGH SELL 45 → +45
    # expected = -40
    fills = [
        FillResult(price=45.0, filled=True, reason="bid_fill"),
        FillResult(price=65.0, filled=True, reason="ask_fill"),
        FillResult(price=65.0, filled=True, reason="ask_fill"),
        FillResult(price=45.0, filled=True, reason="bid_fill"),
    ]
    result = _engine()._cashflow_from_fills(_LONG_BFLY_EXIT, fills, lot_size=1.0, contract_multiplier=1.0)
    assert result == pytest.approx(-40.0)


def test_cashflow_scale_applied_lot_size():
    # Same entry case, lot_size=50 → 60 * 50 = 3000
    fills = [
        FillResult(price=50.0, filled=True, reason="ask_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=50.0, filled=True, reason="ask_fill"),
    ]
    result = _engine()._cashflow_from_fills(_LONG_BFLY_ENTRY, fills, lot_size=50.0, contract_multiplier=1.0)
    assert result == pytest.approx(3000.0)


def test_cashflow_scale_applied_contract_multiplier():
    # Same entry case, contract_multiplier=50 → 60 * 50 = 3000
    fills = [
        FillResult(price=50.0, filled=True, reason="ask_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=80.0, filled=True, reason="bid_fill"),
        FillResult(price=50.0, filled=True, reason="ask_fill"),
    ]
    result = _engine()._cashflow_from_fills(_LONG_BFLY_ENTRY, fills, lot_size=1.0, contract_multiplier=50.0)
    assert result == pytest.approx(3000.0)


# ── Section 03 helpers ────────────────────────────────────────────────────────

_ENTRY_BAR = pd.Timestamp("2024-01-01 10:00:00")


def _engine_with_config(**kwargs):
    engine = object.__new__(BacktestEngine)
    engine.config = BacktestConfig(**kwargs)
    return engine


def _candidate3(direction="LONG_BFLY"):
    return types.SimpleNamespace(
        direction=direction,
        wing_low_contract="LOW",
        body_contract="BODY",
        wing_high_contract="HIGH",
        root_symbol="NIFTY",
        expiry_code="26JAN",
        option_side="CE",
        zscore=2.0,
    )


def _make_chain(
    body_bars: list[tuple],
    skip_wings_at: set | None = None,
    sp1: float | None = 100.0,
    bp1: float | None = 98.0,
    lp: float = 99.0,
    trade_age_seconds: float = 60.0,
):
    """Create a minimal chain for _simulate_exit tests.

    body_bars: [(bar_close, zscore), ...]
    skip_wings_at: set of bar_close values where LOW and HIGH contracts are absent
    """
    skip = skip_wings_at or set()
    rows = []
    for bar, zscore in body_bars:
        sp1_v = float("nan") if sp1 is None else sp1
        bp1_v = float("nan") if bp1 is None else bp1
        rows.append({
            "contract_name": "BODY", "bar_close": bar, "zscore": zscore,
            "sp1": sp1_v, "bp1": bp1_v, "bq1": 50.0, "sq1": 50.0,
            "lp": lp, "trade_age_seconds": trade_age_seconds,
        })
        if bar not in skip:
            for c in ["LOW", "HIGH"]:
                rows.append({
                    "contract_name": c, "bar_close": bar, "zscore": 0.0,
                    "sp1": sp1_v, "bp1": bp1_v, "bq1": 50.0, "sq1": 50.0,
                    "lp": lp, "trade_age_seconds": trade_age_seconds,
                })
    _cols = ["contract_name", "bar_close", "zscore", "sp1", "bp1", "bq1", "sq1", "lp", "trade_age_seconds"]
    chain = pd.DataFrame(rows, columns=_cols) if rows else pd.DataFrame(columns=_cols)
    chain_index = chain.set_index(["bar_close", "contract_name"])
    return chain, chain_index


def _bars(n: int, interval_secs: int = 300) -> list[pd.Timestamp]:
    return [_ENTRY_BAR + pd.Timedelta(seconds=(i + 1) * interval_secs) for i in range(n)]


# ── _fill_leg_with_fallback ───────────────────────────────────────────────────


def test_fill_leg_with_fallback_buy_uses_sp1_when_valid():
    row = pd.Series({"sp1": 105.0, "bp1": 103.0, "bq1": 50.0, "sq1": 50.0, "lp": 100.0})
    result = _engine_with_config()._fill_leg_with_fallback(row, "BUY")
    assert result.filled
    assert result.price == pytest.approx(105.0)
    assert result.reason == "ask_fill"


def test_fill_leg_with_fallback_sell_uses_bp1_when_valid():
    row = pd.Series({"sp1": 105.0, "bp1": 103.0, "bq1": 50.0, "sq1": 50.0, "lp": 100.0})
    result = _engine_with_config()._fill_leg_with_fallback(row, "SELL")
    assert result.filled
    assert result.price == pytest.approx(103.0)
    assert result.reason == "bid_fill"


def test_fill_leg_with_fallback_buy_falls_back_to_lp_when_sp1_nan():
    # half_spread = 0.12 / 4 = 0.03; lp=100 → 103.0
    row = pd.Series({"sp1": float("nan"), "bp1": float("nan"), "lp": 100.0})
    result = _engine_with_config()._fill_leg_with_fallback(row, "BUY")
    assert result.filled
    assert result.price == pytest.approx(103.0)
    assert result.reason == "lp_fallback"


def test_fill_leg_with_fallback_sell_falls_back_to_lp_when_bp1_nan():
    # half_spread = 0.03; lp=100 → 97.0
    row = pd.Series({"sp1": float("nan"), "bp1": float("nan"), "lp": 100.0})
    result = _engine_with_config()._fill_leg_with_fallback(row, "SELL")
    assert result.filled
    assert result.price == pytest.approx(97.0)
    assert result.reason == "lp_fallback"


def test_fill_leg_with_fallback_returns_not_filled_when_both_nan():
    row = pd.Series({"sp1": float("nan"), "bp1": float("nan"), "lp": float("nan")})
    result = _engine_with_config()._fill_leg_with_fallback(row, "BUY")
    assert not result.filled
    assert result.price is None


# ── _simulate_exit ────────────────────────────────────────────────────────────


def test_simulate_exit_profit_take_exit_type():
    bars = list(zip(_bars(3), [2.0, 0.3, 1.0]))  # bar2 z=0.3 <= exit_z=0.5
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config()
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "profit_take"


def test_simulate_exit_stop_loss_exit_type():
    bars = list(zip(_bars(3), [2.0, 4.0, 1.0]))  # bar2 z=4.0 >= stop_z=3.5
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config()
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "stop_loss"


def test_simulate_exit_stop_loss_wins_over_profit_take_at_same_bar():
    # exit_z=4.0, stop_z=0.1 → z=1.0 triggers both; stop_loss wins
    bars = list(zip(_bars(1), [1.0]))
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config(exit_z=4.0, stop_z=0.1)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "stop_loss"


def test_simulate_exit_time_stop_when_no_trigger_fires():
    # z=2.0 all bars: no trigger with default exit_z=0.5, stop_z=3.5
    bars = list(zip(_bars(3), [2.0, 2.0, 2.0]))
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config(holding_bars_5m=3)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "time_stop"


def test_simulate_exit_returns_7_tuple_not_5():
    bars = list(zip(_bars(1), [0.3]))  # profit_take
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config()
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    bar, z, cf, tv, fills, exit_type, fill_quality = result  # must not raise ValueError
    assert len(fills) == 4


def test_simulate_exit_returns_none_when_body_has_no_bars_after_entry():
    chain, chain_index = _make_chain([])  # no bars at all
    engine = _engine_with_config()
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is None


def test_simulate_exit_staleness_guard_sets_degraded_fill_quality():
    # No triggers (z=2.0), sp1/bp1=NaN → lp_fallback, trade_age=900 > 300*2=600 → degraded
    bars = list(zip(_bars(2), [2.0, 2.0]))
    chain, chain_index = _make_chain(bars, sp1=None, bp1=None, lp=100.0, trade_age_seconds=900.0)
    engine = _engine_with_config(holding_bars_5m=2, max_trade_age_seconds=300)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, fill_quality = result
    assert exit_type == "time_stop"
    assert fill_quality == "degraded"


def test_simulate_exit_time_stop_walks_back_when_wing_missing_at_last_bar():
    ts = _bars(3)
    bars = list(zip(ts, [2.0, 2.0, 2.0]))
    # Last bar (ts[2]) is missing LOW and HIGH
    chain, chain_index = _make_chain(bars, skip_wings_at={ts[2]})
    engine = _engine_with_config(holding_bars_5m=3)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    exit_bar, _, _, _, _, exit_type, _ = result
    assert exit_type == "time_stop"
    assert exit_bar == ts[1]  # walked back to bar-1


def test_simulate_exit_time_stop_no_quote_when_no_walkback_succeeds():
    ts = _bars(3)
    bars = list(zip(ts, [2.0, 2.0, 2.0]))
    # All 3 bars missing wings
    chain, chain_index = _make_chain(bars, skip_wings_at=set(ts))
    engine = _engine_with_config(holding_bars_5m=3)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, fill_quality = result
    assert exit_type == "time_stop_no_quote"
    assert fill_quality == "no_quote"


def test_simulate_exit_phase1_fallthrough_when_trigger_bar_missing_quotes():
    # stop_loss trigger fires at bar1 but wings are missing there → falls through to Phase 2
    ts = _bars(3)
    bars = list(zip(ts, [4.0, 2.0, 2.0]))  # bar1 z=4.0 → stop_loss trigger
    chain, chain_index = _make_chain(bars, skip_wings_at={ts[0]})  # wings missing at bar1
    engine = _engine_with_config(holding_bars_5m=3)
    result = engine._simulate_exit(chain, chain_index, _candidate3(), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "time_stop"  # fell through to Phase 2


def test_simulate_exit_short_bfly_profit_take():
    bars = list(zip(_bars(2), [2.0, 0.3]))  # bar2 z=0.3 → profit_take
    chain, chain_index = _make_chain(bars)
    engine = _engine_with_config()
    result = engine._simulate_exit(chain, chain_index, _candidate3("SHORT_BFLY"), _ENTRY_BAR, 1.0, 1.0)
    assert result is not None
    _, _, _, _, _, exit_type, _ = result
    assert exit_type == "profit_take"


# ── Section 04 helpers ────────────────────────────────────────────────────────


def _engine_for_run(sessions=("2024-01-01",), root_symbols=("NIFTY",)):
    engine = object.__new__(BacktestEngine)
    engine.config = BacktestConfig(root_symbols=root_symbols)
    engine.manifest = pd.DataFrame({"session_date": list(sessions)})
    return engine


def _fake_artifact(n_rows: int = 3):
    chain = pd.DataFrame({
        "contract_name": [f"C{i}" for i in range(n_rows)],
        "bar_close": [pd.Timestamp("2024-01-01 10:00")] * n_rows,
    })
    return SessionChainArtifacts(option_bars=chain.copy(), underlying_bars=pd.DataFrame())


def _run_mocked(engine, bsc_effects, chain_rows=3):
    """Run engine.run() with all external deps mocked.

    bsc_effects: list; each element is either an Exception instance (to raise)
                 or None (to return _fake_artifact(chain_rows)).
    Returns (reports, exception) — one will be None.
    """
    effects = list(bsc_effects)
    chain = pd.DataFrame({
        "contract_name": [f"C{i}" for i in range(chain_rows)],
        "bar_close": [pd.Timestamp("2024-01-01 10:00")] * chain_rows,
    })

    def bsc_side(*args, **kwargs):
        e = effects.pop(0)
        if isinstance(e, Exception):
            raise e
        return _fake_artifact(chain_rows)

    _empty_trades = pd.DataFrame(columns=["trade_id"])
    engine._simulate = lambda *a, **kw: (_empty_trades, pd.DataFrame(), pd.DataFrame())

    with unittest.mock.patch("essvi_bfly.backtest.engine.build_session_chain", side_effect=bsc_side), \
         unittest.mock.patch("essvi_bfly.backtest.engine.calibrate_surface",
                             return_value=(chain.copy(), pd.DataFrame())), \
         unittest.mock.patch("essvi_bfly.backtest.engine.add_residual_zscores",
                             side_effect=lambda df, cfg: df), \
         unittest.mock.patch("essvi_bfly.backtest.engine.select_candidates",
                             return_value=pd.DataFrame()):
        try:
            return engine.run(), None
        except Exception as exc:
            return None, exc


# ── _build_nav ────────────────────────────────────────────────────────────────


def test_build_nav_cumulative_pnl():
    rows = [
        {"trade_id": 1, "pnl": 10.0},
        {"trade_id": 2, "pnl": -5.0},
        {"trade_id": 3, "pnl": 20.0},
    ]
    df = _engine_with_config()._build_nav(rows)
    assert list(df["cumulative_pnl"]) == pytest.approx([10.0, 5.0, 25.0])


def test_build_nav_preserves_trade_id():
    rows = [{"trade_id": 7, "pnl": 100.0}, {"trade_id": 3, "pnl": 50.0}]
    df = _engine_with_config()._build_nav(rows)
    assert list(df["trade_id"]) == [3, 7]  # sorted ascending


def test_build_nav_integration_csv_has_cumulative_pnl(tmp_path):
    rows = [{"trade_id": 1, "pnl": 5.0}]
    df = _engine_with_config()._build_nav(rows)
    csv_path = tmp_path / "butterfly_nav.csv"
    df.to_csv(csv_path, index=False)
    reloaded = pd.read_csv(csv_path)
    assert "cumulative_pnl" in reloaded.columns


def test_build_nav_empty_list_returns_correct_columns():
    df = _engine_with_config()._build_nav([])
    expected = {
        "trade_id", "entry_bar", "exit_bar", "entry_zscore", "exit_zscore",
        "theoretical_edge", "entry_cashflow", "exit_cashflow", "transaction_cost",
        "pnl", "cumulative_pnl",
    }
    assert set(df.columns) == expected
    assert len(df) == 0


# ── run() session resilience ──────────────────────────────────────────────────


def test_run_skips_session_on_file_not_found(caplog):
    engine = _engine_for_run(sessions=("2024-01-01", "2024-01-02"))
    with caplog.at_level(logging.WARNING, logger="essvi_bfly.backtest.engine"):
        reports, exc = _run_mocked(engine, [FileNotFoundError("missing"), None])
    assert exc is None
    assert any("Skipping" in r.message for r in caplog.records if r.levelno == logging.WARNING)


def test_run_skips_session_on_oserror(caplog):
    engine = _engine_for_run(sessions=("2024-01-01", "2024-01-02"))
    with caplog.at_level(logging.WARNING, logger="essvi_bfly.backtest.engine"):
        reports, exc = _run_mocked(engine, [OSError("io failure"), None])
    assert exc is None
    assert any("Skipping" in r.message for r in caplog.records if r.levelno == logging.WARNING)


def test_run_does_not_catch_keyerror_from_simulate():
    engine = _engine_for_run(sessions=("2024-01-01",))
    chain = pd.DataFrame({"contract_name": ["C1"], "bar_close": [pd.Timestamp("2024-01-01 10:00")]})
    engine._simulate = unittest.mock.Mock(side_effect=KeyError("unexpected"))
    with unittest.mock.patch("essvi_bfly.backtest.engine.build_session_chain",
                             return_value=_fake_artifact()), \
         unittest.mock.patch("essvi_bfly.backtest.engine.calibrate_surface",
                             return_value=(chain, pd.DataFrame())), \
         unittest.mock.patch("essvi_bfly.backtest.engine.add_residual_zscores",
                             side_effect=lambda df, cfg: df), \
         unittest.mock.patch("essvi_bfly.backtest.engine.select_candidates",
                             return_value=pd.DataFrame(columns=["body_contract"])):
        with pytest.raises(KeyError):
            engine.run()


def test_run_raises_runtime_error_on_zero_rows_all_symbols():
    engine = _engine_for_run(sessions=("2024-01-01",), root_symbols=("NIFTY",))
    _, exc = _run_mocked(engine, [FileNotFoundError("no data")])
    assert isinstance(exc, RuntimeError)


def test_run_raises_runtime_error_on_zero_rows_for_symbol():
    # NIFTY works; BANKNIFTY fails → RuntimeError mentioning BANKNIFTY
    engine = _engine_for_run(sessions=("2024-01-01",), root_symbols=("NIFTY", "BANKNIFTY"))
    _, exc = _run_mocked(engine, [None, FileNotFoundError("no data")])
    assert isinstance(exc, RuntimeError)
    assert "BANKNIFTY" in str(exc)


def test_run_continues_after_data_error():
    engine = _engine_for_run(sessions=("2024-01-01", "2024-01-02"))
    reports, exc = _run_mocked(engine, [FileNotFoundError("fail"), None])
    assert exc is None
    assert reports is not None


# ── _build_contract_bar_index / _next_bar_for_contract ────────────────────────


def _synthetic_chain(contracts: list[str], bars_per_contract: int) -> pd.DataFrame:
    """Build a synthetic chain DataFrame with bar_close and contract_name columns."""
    rows = []
    base = pd.Timestamp("2024-01-01 09:15")
    for c in contracts:
        for i in range(bars_per_contract):
            rows.append({"contract_name": c, "bar_close": base + pd.Timedelta(minutes=5 * i)})
    return pd.DataFrame(rows)


class TestBuildContractBarIndex:
    def test_returns_dict_keyed_by_contract_name(self):
        chain = _synthetic_chain(["A", "B", "C"], 5)
        idx = _engine()._build_contract_bar_index(chain)
        assert isinstance(idx, dict)
        assert set(idx.keys()) == {"A", "B", "C"}

    def test_values_are_sorted_datetimeindex(self):
        chain = _synthetic_chain(["A"], 5).sample(frac=1, random_state=42)
        idx = _engine()._build_contract_bar_index(chain)
        arr = idx["A"]
        assert isinstance(arr, pd.DatetimeIndex)
        assert arr.is_monotonic_increasing

    def test_tz_aware_timestamps_preserved(self):
        base = pd.Timestamp("2024-01-01 09:15", tz="Asia/Kolkata")
        rows = [{"contract_name": "A", "bar_close": base + pd.Timedelta(minutes=5 * i)} for i in range(3)]
        chain = pd.DataFrame(rows)
        idx = _engine()._build_contract_bar_index(chain)
        assert idx["A"].tz is not None
        assert str(idx["A"].tz) == "Asia/Kolkata"

    def test_all_contracts_present(self):
        contracts = ["X1", "X2", "X3", "X4"]
        chain = _synthetic_chain(contracts, 3)
        idx = _engine()._build_contract_bar_index(chain)
        assert set(idx.keys()) == set(contracts)

    def test_empty_chain_returns_empty_dict(self):
        chain = pd.DataFrame(columns=["contract_name", "bar_close"])
        idx = _engine()._build_contract_bar_index(chain)
        assert idx == {}


class TestNextBarForContract:
    def test_returns_first_bar_after_entry(self):
        chain = _synthetic_chain(["A"], 5)
        engine = _engine()
        bar_index = engine._build_contract_bar_index(chain)
        after = pd.Timestamp("2024-01-01 09:15")
        result = engine._next_bar_for_contract(chain, "A", after, bar_index=bar_index)
        assert result == pd.Timestamp("2024-01-01 09:20")

    def test_returns_none_when_no_bar_after_entry(self):
        chain = _synthetic_chain(["A"], 3)
        engine = _engine()
        bar_index = engine._build_contract_bar_index(chain)
        last_bar = pd.Timestamp("2024-01-01 09:25")
        result = engine._next_bar_for_contract(chain, "A", last_bar, bar_index=bar_index)
        assert result is None

    def test_returns_none_for_unknown_contract(self):
        chain = _synthetic_chain(["A"], 5)
        engine = _engine()
        bar_index = engine._build_contract_bar_index(chain)
        result = engine._next_bar_for_contract(chain, "UNKNOWN", pd.Timestamp("2024-01-01 09:15"), bar_index=bar_index)
        assert result is None

    def test_uses_binary_search_not_full_filter(self):
        chain = _synthetic_chain(["A", "B"], 10)
        engine = _engine()
        bar_index = engine._build_contract_bar_index(chain)
        after = pd.Timestamp("2024-01-01 09:30")
        result_indexed = engine._next_bar_for_contract(chain, "A", after, bar_index=bar_index)
        result_legacy = engine._next_bar_for_contract(chain, "A", after)
        assert result_indexed == result_legacy

    @pytest.mark.slow
    def test_performance_10k_lookups(self):
        import time
        contracts = [f"C{i}" for i in range(100)]
        chain = _synthetic_chain(contracts, 75)
        engine = _engine()
        bar_index = engine._build_contract_bar_index(chain)
        after = pd.Timestamp("2024-01-01 09:30")
        start = time.time()
        for _ in range(100):
            for c in contracts:
                engine._next_bar_for_contract(chain, c, after, bar_index=bar_index)
        elapsed = time.time() - start
        assert elapsed < 1.0
