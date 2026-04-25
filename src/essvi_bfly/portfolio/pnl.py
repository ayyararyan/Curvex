from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from essvi_bfly.portfolio.structures import ButterflyTrade


def trades_to_frame(trades: list[ButterflyTrade]) -> pd.DataFrame:
    return pd.DataFrame([asdict(t) for t in trades])
