from __future__ import annotations

import pandas as pd


def generate_bar_schedule(session_date: str, bar_freq: str) -> pd.DatetimeIndex:
    start = pd.Timestamp(f"{session_date.replace('_', '-')}" + " 09:15:00", tz="Asia/Kolkata")
    end = pd.Timestamp(f"{session_date.replace('_', '-')}" + " 15:30:00", tz="Asia/Kolkata")
    return pd.date_range(start=start, end=end, freq=bar_freq)


def sample_state_on_bars(state_events: pd.DataFrame, bars: pd.DatetimeIndex) -> pd.DataFrame:
    if state_events.empty:
        return pd.DataFrame({"bar_close": bars})
    left = pd.DataFrame({"bar_close": bars})
    right = state_events.dropna(subset=["timestamp"]).sort_values("timestamp")
    if right.empty:
        return left
    sampled = pd.merge_asof(left, right, left_on="bar_close", right_on="timestamp", direction="backward")
    return sampled


def sample_state_at_bar_open(state_events: pd.DataFrame, bars: pd.DatetimeIndex, bar_freq: str) -> pd.DataFrame:
    if state_events.empty:
        return pd.DataFrame({"bar_close": bars})
    left = pd.DataFrame({"bar_close": bars, "bar_open": bars - pd.to_timedelta(bar_freq)})
    right = state_events.dropna(subset=["timestamp"]).sort_values("timestamp")
    if right.empty:
        return left
    sampled = pd.merge_asof(left, right, left_on="bar_open", right_on="timestamp", direction="forward")
    sampled = sampled[(sampled["timestamp"].isna()) | (sampled["timestamp"] <= sampled["bar_close"])].copy()
    return sampled


def session_window_mask(df: pd.DataFrame, skip_open_minutes: int, skip_close_minutes: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    session_date = df["bar_close"].dt.normalize()
    start = session_date + pd.to_timedelta(9 * 60 + 15 + skip_open_minutes, unit="m")
    end = session_date + pd.to_timedelta(15 * 60 + 30 - skip_close_minutes, unit="m")
    return (df["bar_close"] >= start) & (df["bar_close"] <= end)
