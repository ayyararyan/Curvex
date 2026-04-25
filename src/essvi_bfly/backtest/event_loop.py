from __future__ import annotations

from essvi_bfly.backtest.engine import BacktestEngine
from essvi_bfly.backtest.straddle_engine import StraddleBacktestEngine
from essvi_bfly.backtest.results import write_results
from essvi_bfly.config import BacktestConfig


def run_backtest(config: BacktestConfig):
    engine = StraddleBacktestEngine(config) if config.strategy == "straddle" else BacktestEngine(config)
    reports = engine.run()
    write_results(config.outputs_dir / "reports", reports, prefix=config.report_prefix)
    return reports
