from __future__ import annotations

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig


def persistence(series: pd.Series) -> pd.Series:
    signs = np.sign(series.fillna(0))
    run = []
    current = 0
    prev = 0
    for sign in signs:
        if sign == 0:
            current = 0
        elif sign == prev:
            current += 1
        else:
            current = 1
        prev = sign
        run.append(current)
    return pd.Series(run, index=series.index)


def add_residual_zscores(chain: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = chain.sort_values(["contract_name", "session_date", "bar_close"]).copy()
    window = config.zscore_window
    group_keys = ["contract_name", "session_date"]
    grouped = out.groupby(group_keys, group_keys=False)["residual_iv"]
    min_periods = min(20, window)
    out["residual_mean_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).mean())
    out["residual_std_roll"] = grouped.transform(lambda s: s.rolling(window, min_periods=min_periods).std())
    out["zscore"] = (out["residual_iv"] - out["residual_mean_roll"]) / out["residual_std_roll"]

    out["same_sign_persistence"] = (
        out.groupby(group_keys, group_keys=False)["zscore"]
        .apply(persistence)
        .reindex(out.index)
    )
    return out
