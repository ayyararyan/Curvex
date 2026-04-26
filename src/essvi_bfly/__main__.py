from __future__ import annotations

import argparse
import logging
import sys

from essvi_bfly.backtest.event_loop import run_backtest
from essvi_bfly.config import BacktestConfig


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    parser = argparse.ArgumentParser(description="Run eSSVI butterfly backtest.")
    parser.add_argument("--strategy", default="butterfly", choices=["butterfly", "straddle"])
    parser.add_argument("--root-symbol", action="append", dest="root_symbols", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--bar-freq", default="5min", choices=["1min", "5min"])
    parser.add_argument("--max-expiries", type=int, default=1)
    args = parser.parse_args()
    config = BacktestConfig(
        strategy=args.strategy,
        root_symbols=tuple(args.root_symbols) if args.root_symbols else ("NIFTY", "BANKNIFTY"),
        start_date=args.start_date,
        end_date=args.end_date,
        bar_freq=args.bar_freq,
        max_expiries_per_session=args.max_expiries,
    )
    run_backtest(config)


if __name__ == "__main__":
    main()
