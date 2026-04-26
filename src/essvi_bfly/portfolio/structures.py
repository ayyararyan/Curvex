from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class TradeLeg:
    contract_name: str
    quantity: int
    side: str
    entry_price: float
    option_side: str


@dataclass(slots=True)
class ButterflyTrade:
    trade_id: int
    root_symbol: str
    expiry_code: str
    direction: str
    entry_bar: pd.Timestamp
    body_contract: str
    wing_low_contract: str
    wing_high_contract: str
    option_side: str
    entry_zscore: float
    entry_cost: float
    exit_bar: pd.Timestamp | None = None
    exit_zscore: float | None = None
    lot_size: float = 1.0
    contract_multiplier: float = 1.0
    status: str = "OPEN"
    # Allowed values: 'profit_take' | 'stop_loss' | 'time_stop' | 'time_stop_no_quote'
    exit_type: str | None = None
    # Allowed values: None (normal) | 'degraded' (stale lp used at time-stop)
    exit_fill_quality: str | None = None
