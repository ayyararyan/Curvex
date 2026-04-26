from __future__ import annotations

import logging
from dataclasses import asdict

import numpy as np
import pandas as pd
import pyarrow

from essvi_bfly.config import BacktestConfig
from essvi_bfly.execution.fills import FillResult, fill_leg
from essvi_bfly.execution.slippage import estimate_transaction_cost
from essvi_bfly.instruments import load_manifest
from essvi_bfly.portfolio.structures import ButterflyTrade
from essvi_bfly.preprocess.option_chain import build_session_chain
from essvi_bfly.signal.candidate_selection import select_candidates
from essvi_bfly.signal.residuals import calibrate_surface
from essvi_bfly.signal.zscores import add_residual_zscores

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.manifest = load_manifest(config.manifest_path)
        self.config.ensure_output_dirs()

    def available_sessions(self) -> list[str]:
        sessions = sorted(self.manifest["session_date"].unique().tolist())

        def _norm(s: str) -> str:
            return s.replace("_", "-")

        if self.config.start_date:
            start = _norm(self.config.start_date)
            sessions = [s for s in sessions if _norm(s) >= start]
        if self.config.end_date:
            end = _norm(self.config.end_date)
            sessions = [s for s in sessions if _norm(s) <= end]
        return sessions

    def run(self) -> dict[str, pd.DataFrame]:
        session_chains: list[pd.DataFrame] = []
        diagnostics_frames: list[pd.DataFrame] = []
        rows_produced: dict[str, int] = {s: 0 for s in self.config.root_symbols}
        for root_symbol in self.config.root_symbols:
            for session_date in self.available_sessions():
                try:
                    artifacts = build_session_chain(self.manifest, session_date, root_symbol, self.config)
                except (FileNotFoundError, pyarrow.ArrowInvalid, pyarrow.ArrowIOError, OSError,  # plan had ArrowInvalidError (typo); correct class is ArrowInvalid
                        pd.errors.EmptyDataError, pd.errors.ParserError) as e:
                    logger.warning("Skipping %s %s — data load failed: %s", root_symbol, session_date, e)
                    continue
                if artifacts.option_bars.empty:
                    logger.warning("Skipping %s %s — empty option chain", root_symbol, session_date)
                    continue
                chain, diagnostics = calibrate_surface(artifacts.option_bars, self.config)
                chain = add_residual_zscores(chain, self.config)
                session_chains.append(chain)
                diagnostics_frames.append(diagnostics)
                rows_produced[root_symbol] += len(chain)
        for symbol in self.config.root_symbols:
            if rows_produced[symbol] == 0:
                raise RuntimeError(
                    f"Zero chain rows produced for symbol {symbol!r}. "
                    "All sessions were skipped, returned empty data, or calibration produced no rows. "
                    "Check session skip warnings above."
                )
        all_chain = pd.concat(session_chains, ignore_index=True) if session_chains else pd.DataFrame()
        all_diagnostics = pd.concat(diagnostics_frames, ignore_index=True) if diagnostics_frames else pd.DataFrame()
        candidates = select_candidates(all_chain, all_diagnostics, self.config)
        if candidates.empty:
            candidates = pd.DataFrame(
                columns=[
                    "bar_close",
                    "root_symbol",
                    "expiry_code",
                    "option_side",
                    "body_contract",
                    "wing_low_contract",
                    "wing_high_contract",
                    "direction",
                    "zscore",
                    "market_premium",
                    "model_premium",
                    "theoretical_edge",
                    "estimated_cost",
                    "lot_size",
                    "contract_multiplier",
                ]
            )
        trades, fills, nav = self._simulate(all_chain, candidates)
        reports = {
            "chain": all_chain,
            "calibration_diagnostics": all_diagnostics,
            "candidates": candidates,
            "fills": fills,
            "trades": trades,
            "nav": nav,
        }
        return reports

    def _simulate(self, chain: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        if candidates.empty:
            return (
                pd.DataFrame(columns=["trade_id", "root_symbol", "expiry_code", "direction", "entry_bar", "body_contract", "wing_low_contract", "wing_high_contract", "option_side", "entry_zscore", "entry_cost", "exit_bar", "exit_zscore", "lot_size", "contract_multiplier", "status", "exit_type", "exit_fill_quality"]),
                pd.DataFrame(columns=["trade_id", "bar_close", "contract_name", "action", "fill_price", "reason"]),
                pd.DataFrame(columns=["trade_id", "entry_bar", "exit_bar", "entry_zscore", "exit_zscore", "theoretical_edge", "transaction_cost", "pnl"]),
            )
        chain_index = chain.set_index(["bar_close", "contract_name"])
        bar_index = self._build_contract_bar_index(chain)
        trades: list[ButterflyTrade] = []
        fills_rows: list[dict] = []
        nav_rows: list[dict] = []
        active_until: dict[tuple[str, str, str, str, str, str], pd.Timestamp] = {}
        trade_id = 1
        for candidate in candidates.sort_values("bar_close").itertuples(index=False):
            structure_key = (
                candidate.root_symbol,
                candidate.expiry_code,
                candidate.direction,
                candidate.body_contract,
                candidate.wing_low_contract,
                candidate.wing_high_contract,
            )
            blocked_until = active_until.get(structure_key)
            if blocked_until is not None and pd.Timestamp(candidate.bar_close) < blocked_until:
                continue
            entry_bar = self._next_bar_for_contract(chain, candidate.body_contract, candidate.bar_close, bar_index=bar_index)
            if entry_bar is None:
                continue
            entry_quotes = self._get_leg_open_quotes(chain_index, entry_bar, candidate)
            if entry_quotes is None:
                continue
            entry_actions = self._build_actions(candidate, entry_quotes, is_exit=False)
            fill_results = [fill_leg(row, action) for action, _, row in entry_actions]
            if not all(fill.filled for fill in fill_results):
                continue
            lot_size = float(getattr(candidate, "lot_size", 1.0) or 1.0)
            contract_multiplier = float(getattr(candidate, "contract_multiplier", 1.0) or 1.0)
            entry_cashflow = self._cashflow_from_fills(entry_actions, fill_results, lot_size, contract_multiplier)
            entry_turnover = self._turnover_from_fills(fill_results, lot_size, contract_multiplier)
            entry_cost = estimate_transaction_cost(
                entry_turnover,
                self.config.fee_rate,
                self.config.tax_rate,
                self.config.leg_brokerage_per_order,
                1,
            )
            exit_result = self._simulate_exit(
                chain,
                chain_index,
                candidate,
                entry_bar,
                lot_size,
                contract_multiplier,
            )
            if exit_result is None:
                continue
            exit_bar, exit_z, exit_cashflow, exit_turnover, exit_fill_results, exit_type, fill_quality = exit_result
            exit_cost = estimate_transaction_cost(
                exit_turnover,
                self.config.fee_rate,
                self.config.tax_rate,
                self.config.leg_brokerage_per_order,
                1,
            )
            transaction_cost = entry_cost + exit_cost
            trade = ButterflyTrade(
                trade_id=trade_id,
                root_symbol=candidate.root_symbol,
                expiry_code=candidate.expiry_code,
                direction=candidate.direction,
                entry_bar=entry_bar,
                body_contract=candidate.body_contract,
                wing_low_contract=candidate.wing_low_contract,
                wing_high_contract=candidate.wing_high_contract,
                option_side=candidate.option_side,
                entry_zscore=float(candidate.zscore),
                entry_cost=float(entry_cost),
                exit_bar=exit_bar,
                exit_zscore=None if exit_z is None else float(exit_z),
                lot_size=lot_size,
                contract_multiplier=contract_multiplier,
                status="CLOSED",
                exit_type=exit_type,
                exit_fill_quality=fill_quality,
            )
            active_until[structure_key] = pd.Timestamp(exit_bar)
            trades.append(trade)
            for (action, contract_name, _), fill in zip(entry_actions, fill_results):
                fills_rows.append(
                    {
                        "trade_id": trade_id,
                        "bar_close": entry_bar,
                        "contract_name": contract_name,
                        "action": action,
                        "fill_price": fill.price,
                        "reason": f"entry_{fill.reason}",
                    }
                )
            if candidate.direction == "LONG_BFLY":
                exit_leg_specs = [
                    ("SELL", candidate.wing_low_contract),
                    ("BUY", candidate.body_contract),
                    ("BUY", candidate.body_contract),
                    ("SELL", candidate.wing_high_contract),
                ]
            else:
                exit_leg_specs = [
                    ("BUY", candidate.wing_low_contract),
                    ("SELL", candidate.body_contract),
                    ("SELL", candidate.body_contract),
                    ("BUY", candidate.wing_high_contract),
                ]
            for (action, contract_name), fill in zip(exit_leg_specs, exit_fill_results):
                fills_rows.append(
                    {
                        "trade_id": trade_id,
                        "bar_close": exit_bar,
                        "contract_name": contract_name,
                        "action": action,
                        "fill_price": fill.price,
                        "reason": f"exit_{fill.reason}",
                    }
                )
            pnl = entry_cashflow + exit_cashflow - transaction_cost
            nav_rows.append(
                {
                    "trade_id": trade_id,
                    "entry_bar": entry_bar,
                    "exit_bar": exit_bar,
                    "entry_zscore": candidate.zscore,
                    "exit_zscore": exit_z,
                    "theoretical_edge": candidate.theoretical_edge,
                    "entry_cashflow": entry_cashflow,
                    "exit_cashflow": exit_cashflow,
                    "transaction_cost": transaction_cost,
                    "pnl": pnl,
                }
            )
            trade_id += 1
        return pd.DataFrame([asdict(t) for t in trades]), pd.DataFrame(fills_rows), self._build_nav(nav_rows)

    def _build_nav(self, nav_rows: list[dict]) -> pd.DataFrame:
        if not nav_rows:
            return pd.DataFrame(columns=[
                "trade_id", "entry_bar", "exit_bar", "entry_zscore", "exit_zscore",
                "theoretical_edge", "entry_cashflow", "exit_cashflow", "transaction_cost",
                "pnl", "cumulative_pnl",
            ])
        df = pd.DataFrame(nav_rows)
        df = df.sort_values("trade_id").reset_index(drop=True)
        df["cumulative_pnl"] = df["pnl"].cumsum()
        return df

    def _build_contract_bar_index(self, chain: pd.DataFrame) -> dict[str, pd.DatetimeIndex]:
        """Pre-compute sorted bar_close DatetimeIndex per contract_name.

        Returns dict mapping contract_name → sorted pd.DatetimeIndex of bar_close timestamps.
        Preserves timezone (e.g. Asia/Kolkata) so searchsorted comparisons stay tz-aware.
        Used by _next_bar_for_contract for O(log N) lookup via DatetimeIndex.searchsorted.
        Called once before the candidate loop in _simulate.

        Note: index is static — do not use with a streaming/appended chain.
        """
        index: dict[str, pd.DatetimeIndex] = {}
        for contract_name, group in chain.groupby("contract_name", sort=False):
            unique_bars = group["bar_close"].dropna().drop_duplicates().sort_values()
            index[contract_name] = pd.DatetimeIndex(unique_bars)
        return index

    def _next_bar_for_contract(
        self,
        chain: pd.DataFrame,
        contract_name: str,
        after_bar: pd.Timestamp,
        bar_index: dict[str, pd.DatetimeIndex] | None = None,
    ) -> pd.Timestamp | None:
        """Return the first bar_close strictly after after_bar for contract_name.

        If bar_index provided: O(log N) via DatetimeIndex.searchsorted (tz-aware).
        If bar_index is None: legacy O(N) DataFrame filter (backward compat).
        Returns None if contract absent or no bar exists after after_bar.
        """
        if bar_index is not None:
            arr = bar_index.get(contract_name)
            if arr is None or len(arr) == 0:
                return None
            i = arr.searchsorted(after_bar, side="right")
            if i >= len(arr):
                return None
            return arr[i]
        contract_rows = chain[chain["contract_name"] == contract_name].sort_values("bar_close")
        later = contract_rows.loc[contract_rows["bar_close"] > after_bar, "bar_close"]
        if later.empty:
            return None
        return later.iloc[0]

    def _get_leg_quotes(self, chain_index: pd.DataFrame, bar_close: pd.Timestamp, candidate):
        keys = [
            (bar_close, candidate.wing_low_contract),
            (bar_close, candidate.body_contract),
            (bar_close, candidate.wing_high_contract),
        ]
        if any(key not in chain_index.index for key in keys):
            return None
        return (
            chain_index.loc[keys[0]],
            chain_index.loc[keys[1]],
            chain_index.loc[keys[2]],
        )

    def _get_leg_open_quotes(self, chain_index: pd.DataFrame, bar_close: pd.Timestamp, candidate):
        leg_quotes = self._get_leg_quotes(chain_index, bar_close, candidate)
        if leg_quotes is None:
            return None
        out = []
        for row in leg_quotes:
            open_row = row.copy()
            for src, dst in [("open_bp1", "bp1"), ("open_sp1", "sp1"), ("open_bq1", "bq1"), ("open_sq1", "sq1")]:
                if src in open_row.index and pd.notna(open_row[src]):
                    open_row[dst] = open_row[src]
            out.append(open_row)
        return tuple(out)

    def _build_actions(self, candidate, leg_quotes, is_exit: bool):
        low, body, high = leg_quotes
        if candidate.direction == "LONG_BFLY":
            if not is_exit:
                return [
                    ("BUY", candidate.wing_low_contract, low),
                    ("SELL", candidate.body_contract, body),
                    ("SELL", candidate.body_contract, body),
                    ("BUY", candidate.wing_high_contract, high),
                ]
            return [
                ("SELL", candidate.wing_low_contract, low),
                ("BUY", candidate.body_contract, body),
                ("BUY", candidate.body_contract, body),
                ("SELL", candidate.wing_high_contract, high),
            ]
        if not is_exit:
            return [
                ("SELL", candidate.wing_low_contract, low),
                ("BUY", candidate.body_contract, body),
                ("BUY", candidate.body_contract, body),
                ("SELL", candidate.wing_high_contract, high),
            ]
        return [
            ("BUY", candidate.wing_low_contract, low),
            ("SELL", candidate.body_contract, body),
            ("SELL", candidate.body_contract, body),
            ("BUY", candidate.wing_high_contract, high),
        ]

    def _cashflow_from_fills(self, actions, fills, lot_size: float, contract_multiplier: float) -> float:
        scale = lot_size * contract_multiplier
        return sum(
            (
                (fill.price if fill.price is not None else 0.0)
                if action == "SELL"
                else -(fill.price if fill.price is not None else 0.0)
            ) * scale
            for (action, _, _), fill in zip(actions, fills)
        )

    def _turnover_from_fills(self, fills, lot_size: float, contract_multiplier: float) -> float:
        scale = lot_size * contract_multiplier
        return sum(abs(fill.price if fill.price is not None else 0.0) * scale for fill in fills)

    def _fill_leg_with_fallback(self, quote_row: pd.Series, action: str) -> FillResult:
        half_spread = self.config.max_spread_pct / 4
        if action == "BUY":
            sp1 = quote_row.get("sp1")
            if pd.notna(sp1) and sp1 > 0:
                return FillResult(float(sp1), True, "ask_fill")
            lp = quote_row.get("lp")
            if pd.notna(lp) and lp > 0:
                return FillResult(float(lp) * (1 + half_spread), True, "lp_fallback")
            return FillResult(None, False, "no_quote")
        bp1 = quote_row.get("bp1")
        if pd.notna(bp1) and bp1 > 0:
            return FillResult(float(bp1), True, "bid_fill")
        lp = quote_row.get("lp")
        if pd.notna(lp) and lp > 0:
            return FillResult(float(lp) * (1 - half_spread), True, "lp_fallback")
        return FillResult(None, False, "no_quote")

    def _simulate_exit(
        self,
        chain: pd.DataFrame,
        chain_index: pd.DataFrame,
        candidate,
        entry_bar: pd.Timestamp,
        lot_size: float,
        contract_multiplier: float,
    ) -> tuple[pd.Timestamp, float | None, float, float, list, str, str | None] | None:
        contract_rows = chain[chain["contract_name"] == candidate.body_contract].sort_values("bar_close")
        later = contract_rows[contract_rows["bar_close"] > entry_bar].head(self.config.max_holding_bars)
        if later.empty:
            return None

        # Phase 1: primary exit (trigger-based)
        for row in later.itertuples(index=False):
            z = getattr(row, "zscore", np.nan)
            is_stop_loss = abs(z) >= self.config.stop_z
            is_profit_take = abs(z) <= self.config.exit_z
            if is_stop_loss or is_profit_take:
                exit_type = "stop_loss" if is_stop_loss else "profit_take"
                leg_quotes = self._get_leg_open_quotes(chain_index, row.bar_close, candidate)
                if leg_quotes is None:
                    continue
                exit_actions = self._build_actions(candidate, leg_quotes, is_exit=True)
                fills = [fill_leg(q, action) for action, _, q in exit_actions]
                if all(fill.filled for fill in fills):
                    cf = self._cashflow_from_fills(exit_actions, fills, lot_size, contract_multiplier)
                    tv = self._turnover_from_fills(fills, lot_size, contract_multiplier)
                    return row.bar_close, z, cf, tv, fills, exit_type, None

        # Phase 2: time-stop fallback — walk back up to 3 bars from tail
        tail_rows = list(later.itertuples(index=False))[-3:]
        time_stop_bar = None
        time_stop_quotes = None
        time_stop_z: float | None = None
        for ts_row in reversed(tail_rows):
            quotes = self._get_leg_open_quotes(chain_index, ts_row.bar_close, candidate)
            if quotes is not None:
                time_stop_bar = ts_row.bar_close
                time_stop_z = getattr(ts_row, "zscore", np.nan)
                time_stop_quotes = quotes
                break

        if time_stop_quotes is not None:
            exit_actions = self._build_actions(candidate, time_stop_quotes, is_exit=True)
            fills = [self._fill_leg_with_fallback(q, action) for action, _, q in exit_actions]
            fill_quality: str | None = None
            for (_, _, q), fill in zip(exit_actions, fills):
                age = q.get("trade_age_seconds")
                if fill.reason == "lp_fallback" and pd.notna(age) and age > self.config.max_trade_age_seconds * 2:
                    fill_quality = "degraded"
                    break
            cf = self._cashflow_from_fills(exit_actions, fills, lot_size, contract_multiplier)
            tv = self._turnover_from_fills(fills, lot_size, contract_multiplier)
            return time_stop_bar, time_stop_z, cf, tv, fills, "time_stop", fill_quality

        # No walkback succeeded: time_stop_no_quote
        last_row = list(later.itertuples(index=False))[-1]
        no_fills = [FillResult(None, False, "no_quote")] * 4
        return last_row.bar_close, getattr(last_row, "zscore", np.nan), 0.0, 0.0, no_fills, "time_stop_no_quote", "no_quote"
