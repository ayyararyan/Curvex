import types

import pandas as pd
import pytest

from essvi_bfly.backtest.engine import BacktestEngine
from essvi_bfly.execution.fills import FillResult


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
