from __future__ import annotations

import pandas as pd

from essvi_bfly.backtest.results import write_results
from essvi_bfly.config import BacktestConfig
from essvi_bfly.execution.fills import fill_leg
from essvi_bfly.execution.slippage import estimate_transaction_cost
from essvi_bfly.instruments import load_manifest
from essvi_bfly.preprocess.option_chain import build_session_chain
from essvi_bfly.signal.residuals import calibrate_surface
from essvi_bfly.signal.straddle_selection import build_straddle_chain, select_straddle_candidates
from essvi_bfly.signal.zscores import add_residual_zscores


class StraddleBacktestEngine:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.manifest = load_manifest(config.manifest_path)
        self.config.ensure_output_dirs()

    def available_sessions(self) -> list[str]:
        sessions = sorted(self.manifest["session_date"].unique().tolist())
        if self.config.start_date:
            sessions = [s for s in sessions if s >= self.config.start_date]
        if self.config.end_date:
            sessions = [s for s in sessions if s <= self.config.end_date]
        return sessions

    def run(self) -> dict[str, pd.DataFrame]:
        session_chains: list[pd.DataFrame] = []
        diagnostics_frames: list[pd.DataFrame] = []
        for root_symbol in self.config.root_symbols:
            for session_date in self.available_sessions():
                artifacts = build_session_chain(self.manifest, session_date, root_symbol, self.config)
                chain, diagnostics = calibrate_surface(artifacts.option_bars, self.config)
                chain = add_residual_zscores(chain, self.config)
                session_chains.append(chain)
                diagnostics_frames.append(diagnostics)
        all_chain = pd.concat(session_chains, ignore_index=True) if session_chains else pd.DataFrame()
        all_diagnostics = pd.concat(diagnostics_frames, ignore_index=True) if diagnostics_frames else pd.DataFrame()
        straddle_chain = build_straddle_chain(all_chain, all_diagnostics, self.config)
        candidates = select_straddle_candidates(straddle_chain, self.config)
        trades, fills, nav = self._simulate(straddle_chain, candidates)
        return {
            "straddle_chain": straddle_chain,
            "straddle_candidates": candidates,
            "straddle_trades": trades,
            "straddle_fills": fills,
            "straddle_nav": nav,
        }

    def _get_next_bar(self, df: pd.DataFrame, expiry_code, strike, after_bar):
        later = df[(df["expiry_code"] == expiry_code) & (df["strike"] == strike) & (df["bar_close"] > after_bar)]["bar_close"]
        if later.empty:
            return None
        return later.iloc[0]

    def _get_row(self, df: pd.DataFrame, bar_close, call_contract, put_contract):
        row = df[(df["bar_close"] == bar_close) & (df["call_contract"] == call_contract) & (df["put_contract"] == put_contract)]
        if row.empty:
            return None
        return row.iloc[0].copy()

    def _prep_open_quotes(self, row: pd.Series) -> tuple[pd.Series, pd.Series]:
        call = pd.Series({
            "bp1": row.get("call_open_bp1", row.get("call_bp1")),
            "sp1": row.get("call_open_sp1", row.get("call_sp1")),
            "bq1": row.get("call_open_bq1", row.get("call_bq1")),
            "sq1": row.get("call_open_sq1", row.get("call_sq1")),
        })
        put = pd.Series({
            "bp1": row.get("put_open_bp1", row.get("put_bp1")),
            "sp1": row.get("put_open_sp1", row.get("put_sp1")),
            "bq1": row.get("put_open_bq1", row.get("put_bq1")),
            "sq1": row.get("put_open_sq1", row.get("put_sq1")),
        })
        return call, put

    def _build_actions(self, direction: str, call_quote: pd.Series, put_quote: pd.Series, is_exit: bool):
        if direction == "LONG_STRADDLE":
            return [("SELL" if is_exit else "BUY", "CALL", call_quote), ("SELL" if is_exit else "BUY", "PUT", put_quote)]
        return [("BUY" if is_exit else "SELL", "CALL", call_quote), ("BUY" if is_exit else "SELL", "PUT", put_quote)]

    def _simulate(self, straddle_chain: pd.DataFrame, candidates: pd.DataFrame):
        trade_rows = []
        fill_rows = []
        nav_rows = []
        trade_id = 1
        for candidate in candidates.sort_values(["bar_close", "expiry_code", "strike"]).itertuples(index=False):
            entry_bar = self._get_next_bar(straddle_chain, candidate.expiry_code, candidate.strike, candidate.bar_close)
            if entry_bar is None:
                continue
            entry_row = self._get_row(straddle_chain, entry_bar, candidate.call_contract, candidate.put_contract)
            if entry_row is None:
                continue
            call_quote, put_quote = self._prep_open_quotes(entry_row)
            entry_actions = self._build_actions(candidate.direction, call_quote, put_quote, is_exit=False)
            entry_fills = [fill_leg(q, a) for a, _, q in entry_actions]
            if not all(f.filled for f in entry_fills):
                continue
            later = straddle_chain[
                (straddle_chain["expiry_code"] == candidate.expiry_code)
                & (straddle_chain["strike"] == candidate.strike)
                & (straddle_chain["bar_close"] > entry_bar)
            ].sort_values("bar_close").head(self.config.max_holding_bars)
            if later.empty:
                continue
            exit_bar = None
            exit_z = None
            for row in later.itertuples(index=False):
                if abs(getattr(row, "zscore", float("nan"))) <= self.config.exit_z or abs(getattr(row, "zscore", float("nan"))) >= self.config.stop_z:
                    exit_bar = row.bar_close
                    exit_z = row.zscore
                    break
            if exit_bar is None:
                exit_bar = later.iloc[-1]["bar_close"]
                exit_z = later.iloc[-1]["zscore"]
            exit_row = self._get_row(straddle_chain, exit_bar, candidate.call_contract, candidate.put_contract)
            if exit_row is None:
                continue
            call_exit, put_exit = self._prep_open_quotes(exit_row)
            exit_actions = self._build_actions(candidate.direction, call_exit, put_exit, is_exit=True)
            exit_fills = [fill_leg(q, a) for a, _, q in exit_actions]
            if not all(f.filled for f in exit_fills):
                continue
            scale = float(candidate.lot_size) * float(candidate.contract_multiplier)
            entry_cf = sum((f.price if a == "SELL" else -f.price) * scale for (a, _, _), f in zip(entry_actions, entry_fills))
            exit_cf = sum((f.price if a == "SELL" else -f.price) * scale for (a, _, _), f in zip(exit_actions, exit_fills))
            entry_turn = sum(abs(f.price) * scale for f in entry_fills)
            exit_turn = sum(abs(f.price) * scale for f in exit_fills)
            cost = estimate_transaction_cost(entry_turn, self.config.fee_rate, self.config.tax_rate, self.config.leg_brokerage_per_order, 1)
            cost += estimate_transaction_cost(exit_turn, self.config.fee_rate, self.config.tax_rate, self.config.leg_brokerage_per_order, 1)
            pnl = entry_cf + exit_cf - cost
            trade_rows.append(
                {
                    "trade_id": trade_id,
                    "direction": candidate.direction,
                    "entry_bar": entry_bar,
                    "exit_bar": exit_bar,
                    "expiry_code": candidate.expiry_code,
                    "strike": candidate.strike,
                    "call_contract": candidate.call_contract,
                    "put_contract": candidate.put_contract,
                    "entry_zscore": candidate.zscore,
                    "exit_zscore": exit_z,
                    "lot_size": candidate.lot_size,
                    "contract_multiplier": candidate.contract_multiplier,
                }
            )
            for (action, leg, _), fill in zip(entry_actions, entry_fills):
                fill_rows.append({"trade_id": trade_id, "bar_close": entry_bar, "leg": leg, "action": action, "fill_price": fill.price, "reason": f"entry_{fill.reason}"})
            for (action, leg, _), fill in zip(exit_actions, exit_fills):
                fill_rows.append({"trade_id": trade_id, "bar_close": exit_bar, "leg": leg, "action": action, "fill_price": fill.price, "reason": f"exit_{fill.reason}"})
            nav_rows.append(
                {
                    "trade_id": trade_id,
                    "entry_bar": entry_bar,
                    "exit_bar": exit_bar,
                    "entry_zscore": candidate.zscore,
                    "exit_zscore": exit_z,
                    "theoretical_edge": candidate.theoretical_edge,
                    "entry_cashflow": entry_cf,
                    "exit_cashflow": exit_cf,
                    "transaction_cost": cost,
                    "pnl": pnl,
                }
            )
            trade_id += 1
        return pd.DataFrame(trade_rows), pd.DataFrame(fill_rows), pd.DataFrame(nav_rows)
