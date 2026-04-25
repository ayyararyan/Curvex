from __future__ import annotations

import numpy as np
import pandas as pd

QUOTE_COLS = [f"{prefix}{level}" for prefix in ("bp", "sp", "bq", "sq", "bo", "so") for level in range(1, 6)]
TRADE_COLS = ["lp", "ltq", "ltt", "v", "ap", "pc"]
OI_COLS = ["oi", "poi", "tbq", "tsq"]
META_COLS = ["ls", "ti", "pp", "ml", "uc", "lc", "ue", "le"]


def reconstruct_state_events(df: pd.DataFrame) -> pd.DataFrame:
    state = df.copy()
    state["_raw_order"] = np.arange(len(state))
    state = state.sort_values(["ft", "timestamp", "_raw_order"], kind="mergesort").drop_duplicates()
    for col in QUOTE_COLS + TRADE_COLS + OI_COLS + META_COLS:
        if col in state.columns:
            state[col] = state[col].ffill()
    quote_time = pd.Series(pd.NaT, index=state.index, dtype="datetime64[ns, Asia/Kolkata]")
    trade_time = pd.Series(pd.NaT, index=state.index, dtype="datetime64[ns, Asia/Kolkata]")
    quote_update_mask = state[[c for c in QUOTE_COLS if c in state.columns]].notna().any(axis=1)
    trade_update_mask = state[[c for c in TRADE_COLS if c in state.columns]].notna().any(axis=1)
    quote_time.loc[quote_update_mask] = state.loc[quote_update_mask, "timestamp"]
    trade_time.loc[trade_update_mask] = state.loc[trade_update_mask, "timestamp"]
    state["last_quote_timestamp"] = quote_time.ffill()
    state["last_trade_timestamp"] = trade_time.ffill()
    state["quote_age_seconds"] = (state["timestamp"] - state["last_quote_timestamp"]).dt.total_seconds()
    state["trade_age_seconds"] = (state["timestamp"] - state["last_trade_timestamp"]).dt.total_seconds()
    bid = state["bp1"] if "bp1" in state.columns else pd.Series(np.nan, index=state.index)
    ask = state["sp1"] if "sp1" in state.columns else pd.Series(np.nan, index=state.index)
    state["has_valid_bid"] = bid.fillna(0) > 0
    state["has_valid_ask"] = ask.fillna(0) > 0
    state["has_valid_two_sided_quote"] = state["has_valid_bid"] & state["has_valid_ask"]
    state["is_crossed_market"] = state["has_valid_two_sided_quote"] & (bid > ask)
    state["is_zero_market"] = bid.fillna(0).eq(0) & ask.fillna(0).eq(0)
    return state.reset_index(drop=True)
