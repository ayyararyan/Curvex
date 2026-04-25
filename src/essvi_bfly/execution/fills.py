from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class FillResult:
    price: float | None
    filled: bool
    reason: str


def fill_leg(quote_row: pd.Series, action: str) -> FillResult:
    if action == "BUY":
        ask = quote_row.get("sp1")
        size = quote_row.get("sq1")
        if pd.notna(ask) and ask > 0 and pd.notna(size) and size > 0:
            return FillResult(float(ask), True, "ask_fill")
    else:
        bid = quote_row.get("bp1")
        size = quote_row.get("bq1")
        if pd.notna(bid) and bid > 0 and pd.notna(size) and size > 0:
            return FillResult(float(bid), True, "bid_fill")
    return FillResult(None, False, "no_size_or_quote")
