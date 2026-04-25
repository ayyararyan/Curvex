from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from essvi_bfly.config import BacktestConfig
from essvi_bfly.instruments import build_session_file_map, resolve_expiry_datetime
from essvi_bfly.io.parquet_loader import load_parquet
from essvi_bfly.preprocess.bars import generate_bar_schedule, sample_state_at_bar_open, sample_state_on_bars
from essvi_bfly.preprocess.normalize import normalize_market_frame
from essvi_bfly.preprocess.state_reconstruction import reconstruct_state_events


@dataclass(slots=True)
class SessionChainArtifacts:
    option_bars: pd.DataFrame
    underlying_bars: pd.DataFrame


YEAR_SECONDS = 365.25 * 24 * 3600


def _col_or_default(df: pd.DataFrame, column: str, default: float | bool | pd.Timestamp | None = np.nan) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series(default, index=df.index)


def _load_and_sample(path: str, session_date: str, bar_freq: str) -> pd.DataFrame:
    raw = load_parquet(path)
    norm = normalize_market_frame(raw)
    state = reconstruct_state_events(norm)
    bars = generate_bar_schedule(session_date, bar_freq)
    close_sample = sample_state_on_bars(state, bars)
    open_sample = sample_state_at_bar_open(state, bars, bar_freq)
    open_bid = _col_or_default(open_sample, "bp1")
    open_ask = _col_or_default(open_sample, "sp1")
    open_sample["open_mid"] = np.where(
        open_bid.fillna(0) > 0,
        np.where(open_ask.fillna(0) > 0, (open_bid + open_ask) / 2.0, np.nan),
        np.nan,
    )
    open_sample["open_spread"] = open_ask - open_bid
    open_sample["open_spread_pct"] = open_sample["open_spread"] / open_sample["open_mid"]
    rename_map = {
        "bp1": "open_bp1",
        "sp1": "open_sp1",
        "bq1": "open_bq1",
        "sq1": "open_sq1",
        "timestamp": "open_timestamp",
    }
    open_sample = open_sample.rename(columns=rename_map)
    keep_cols = ["bar_close"] + [c for c in ["open_bp1", "open_sp1", "open_bq1", "open_sq1", "open_timestamp", "open_mid", "open_spread", "open_spread_pct"] if c in open_sample.columns]
    return close_sample.merge(open_sample[keep_cols], on="bar_close", how="left")


def _choose_future_contracts(
    manifest: pd.DataFrame,
    session_date: str,
    root_symbol: str,
    option_expiries: pd.DataFrame,
) -> pd.DataFrame:
    fut_meta = build_session_file_map(manifest, session_date, root_symbol)
    fut_meta = fut_meta[fut_meta["instrument_type"] == "FUT"].copy()
    if fut_meta.empty or option_expiries.empty:
        return pd.DataFrame()
    fut_meta["future_expiry_dt"] = fut_meta["expiry_code"].map(lambda code: resolve_expiry_datetime(root_symbol, code))
    fut_meta = fut_meta.sort_values("future_expiry_dt").reset_index(drop=True)

    selected_rows: list[dict] = []
    for row in option_expiries.itertuples(index=False):
        later = fut_meta[fut_meta["future_expiry_dt"] >= row.expiry_dt]
        chosen = later.iloc[0] if not later.empty else fut_meta.iloc[-1]
        selected_rows.append(
            {
                "option_expiry_code": row.expiry_code,
                "option_expiry_dt": row.expiry_dt,
                "future_contract_name": chosen["contract_name"],
                "future_expiry_code": chosen["expiry_code"],
                "future_expiry_dt": chosen["future_expiry_dt"],
                "resolved_path": chosen["resolved_path"],
            }
        )
    return pd.DataFrame(selected_rows)


def _load_future_forwards(
    manifest: pd.DataFrame,
    session_date: str,
    root_symbol: str,
    option_expiries: pd.DataFrame,
    bar_freq: str,
) -> pd.DataFrame:
    selected = _choose_future_contracts(manifest, session_date, root_symbol, option_expiries)
    if selected.empty:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for row in selected.itertuples(index=False):
        sampled = _load_and_sample(row.resolved_path, session_date, bar_freq)
        sampled["option_expiry_code"] = row.option_expiry_code
        sampled["future_contract_name"] = row.future_contract_name
        sampled["future_expiry_code"] = row.future_expiry_code
        sampled["future_expiry_dt"] = row.future_expiry_dt
        sampled["future_price"] = sampled.get("lp", np.nan)
        future_bid = _col_or_default(sampled, "bp1")
        future_ask = _col_or_default(sampled, "sp1")
        sampled["future_mid"] = np.where(
            (future_bid.fillna(0) > 0) & (future_ask.fillna(0) > 0),
            (future_bid + future_ask) / 2.0,
            _col_or_default(sampled, "lp"),
        )
        sampled["future_quote_ok"] = (
            _col_or_default(sampled, "has_valid_two_sided_quote", False).fillna(False)
            & (~_col_or_default(sampled, "is_crossed_market", False).fillna(False))
            & sampled["future_mid"].fillna(0).gt(0)
        )
        keep_cols = [
            "bar_close",
            "option_expiry_code",
            "future_contract_name",
            "future_expiry_code",
            "future_expiry_dt",
            "future_price",
            "future_mid",
            "future_quote_ok",
        ]
        frames.append(sampled[keep_cols])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_session_chain(
    manifest: pd.DataFrame,
    session_date: str,
    root_symbol: str,
    config: BacktestConfig,
) -> SessionChainArtifacts:
    bars = generate_bar_schedule(session_date, config.bar_freq)
    underlying_contract = config.underlying_spot_map[root_symbol]
    underlying_meta = manifest[
        (manifest["session_date"] == session_date) & (manifest["contract_name"] == underlying_contract)
    ].iloc[0]
    underlying_bars = _load_and_sample(underlying_meta["resolved_path"], session_date, config.bar_freq)
    underlying_bars["underlying_price"] = underlying_bars["lp"]
    option_meta = build_session_file_map(manifest, session_date, root_symbol)
    option_meta = option_meta[option_meta["instrument_type"] == "OPT"].copy()
    if config.max_expiries_per_session:
        option_meta["expiry_dt"] = option_meta["expiry_code"].map(lambda code: resolve_expiry_datetime(root_symbol, code))
        option_meta = option_meta.sort_values(["expiry_dt", "strike"])
        keep_expiries = option_meta["expiry_code"].drop_duplicates().head(config.max_expiries_per_session).tolist()
        option_meta = option_meta[option_meta["expiry_code"].isin(keep_expiries)].copy()
    option_expiries = option_meta[["expiry_code", "expiry_dt"]].drop_duplicates().copy()
    future_bars = _load_future_forwards(manifest, session_date, root_symbol, option_expiries, config.bar_freq)
    frames: list[pd.DataFrame] = []
    for row in option_meta.itertuples(index=False):
        sampled = _load_and_sample(row.resolved_path, session_date, config.bar_freq)
        sampled["session_date"] = session_date
        sampled["root_symbol"] = root_symbol
        sampled["contract_name"] = row.contract_name
        sampled["option_side"] = row.option_side
        sampled["strike"] = float(row.strike) if row.strike else np.nan
        sampled["expiry_code"] = row.expiry_code
        sampled["expiry_dt"] = resolve_expiry_datetime(root_symbol, row.expiry_code)
        bid = _col_or_default(sampled, "bp1")
        ask = _col_or_default(sampled, "sp1")
        sampled["mid"] = np.where(
            (bid.fillna(0) > 0) & (ask.fillna(0) > 0),
            (bid + ask) / 2.0,
            np.nan,
        )
        sampled["spread"] = ask - bid
        sampled["spread_pct"] = sampled["spread"] / sampled["mid"]
        sampled["lot_size"] = _col_or_default(sampled, "ls")
        sampled["contract_multiplier"] = _col_or_default(sampled, "ml")
        frames.append(sampled)
    option_bars = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame({"bar_close": bars})
    option_bars = option_bars.merge(
        underlying_bars[["bar_close", "underlying_price"]],
        on="bar_close",
        how="left",
    )
    if not future_bars.empty:
        option_bars = option_bars.merge(
            future_bars,
            left_on=["bar_close", "expiry_code"],
            right_on=["bar_close", "option_expiry_code"],
            how="left",
        ).drop(columns=["option_expiry_code"], errors="ignore")
    option_bars["tau_years"] = (
        (option_bars["expiry_dt"] - option_bars["bar_close"]).dt.total_seconds() / YEAR_SECONDS
    )
    option_bars["minutes_to_expiry"] = (
        (option_bars["expiry_dt"] - option_bars["bar_close"]).dt.total_seconds() / 60.0
    )
    option_bars["future_tau_years"] = (
        (option_bars["future_expiry_dt"] - option_bars["bar_close"]).dt.total_seconds() / YEAR_SECONDS
    )
    option_bars["future_reference_price"] = np.where(
        option_bars.get("future_quote_ok", False).fillna(False),
        option_bars.get("future_mid", np.nan),
        option_bars.get("future_price", np.nan),
    )
    valid_basis = (
        option_bars["underlying_price"].fillna(0).gt(0)
        & option_bars["future_reference_price"].fillna(0).gt(0)
        & option_bars["future_tau_years"].fillna(0).gt(0)
    )
    option_bars["basis_rate"] = np.where(
        valid_basis,
        np.log(option_bars["future_reference_price"] / option_bars["underlying_price"]) / option_bars["future_tau_years"],
        np.nan,
    )
    carry_forward = option_bars["underlying_price"] * np.exp((config.risk_free_rate - config.carry_rate) * option_bars["tau_years"].clip(lower=0))
    futures_forward = option_bars["underlying_price"] * np.exp(option_bars["basis_rate"] * option_bars["tau_years"].clip(lower=0))
    option_bars["forward"] = np.where(valid_basis, futures_forward, carry_forward)
    option_bars["forward_source"] = np.where(valid_basis, "future_basis", "spot_carry")
    option_bars["is_same_day_expiry"] = option_bars["minutes_to_expiry"] <= (24 * 60)
    option_bars["quote_ok"] = (
        _col_or_default(option_bars, "has_valid_two_sided_quote", False).fillna(False)
        & (~_col_or_default(option_bars, "is_crossed_market", False).fillna(False))
        & (option_bars["mid"].fillna(0) > 0)
    )
    option_bars["lot_size"] = option_bars["lot_size"].fillna(1.0)
    option_bars["contract_multiplier"] = option_bars["contract_multiplier"].fillna(1.0)
    return SessionChainArtifacts(option_bars=option_bars, underlying_bars=underlying_bars)
