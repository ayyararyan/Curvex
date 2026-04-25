from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(slots=True)
class BacktestConfig:
    repo_root: Path = Path("/Volumes/One Touch/NSE/onesec/curvex")
    data_dir: Path = Path("/Volumes/One Touch/NSE/onesec/curvex/data")
    manifest_path: Path = Path("/Volumes/One Touch/NSE/onesec/curvex/data/metadata/MANIFEST.csv")
    inventory_path: Path = Path("/Volumes/One Touch/NSE/onesec/curvex/data/metadata/CONTRACTS_INVENTORY.csv")
    raw_dir: Path = Path("/Volumes/One Touch/NSE/onesec/curvex/data/raw/january_2026")
    outputs_dir: Path = Path("/Volumes/One Touch/NSE/onesec/curvex/outputs/essvi_bfly")
    strategy: str = "butterfly"
    bar_freq: str = "5min"
    root_symbols: Sequence[str] = ("NIFTY", "BANKNIFTY")
    start_date: str | None = None
    end_date: str | None = None
    max_expiries_per_session: int | None = 1
    min_quote_size: float = 1.0
    max_quote_age_seconds: int = 600
    max_trade_age_seconds: int = 300
    max_spread_pct: float = 0.12
    min_option_premium: float = 0.10
    max_same_day_expiry_minutes: int = 15
    skip_open_minutes: int = 15
    skip_close_minutes: int = 15
    risk_free_rate: float = 0.06
    carry_rate: float = 0.00
    entry_z: float = 1.5
    exit_z: float = 0.5
    stop_z: float = 3.5
    persistence_bars_1m: int = 2
    persistence_bars_5m: int = 2
    holding_bars_1m: int = 20
    holding_bars_5m: int = 8
    zscore_window_1m: int = 375
    zscore_window_5m: int = 75
    calibration_rmse_limit: float = 0.02
    min_slice_strikes: int = 3
    atm_weight_width: float = 0.03
    min_edge_to_cost_ratio: float = 1.5
    require_positive_edge: bool = True
    enforce_otm_structure_side: bool = True
    leg_brokerage_per_order: float = 20.0
    fee_rate: float = 0.0005
    tax_rate: float = 0.0005
    warm_start: bool = True
    write_intermediate: bool = True
    underlying_spot_map: dict[str, str] = field(
        default_factory=lambda: {
            "NIFTY": "NIFTY50",
            "BANKNIFTY": "NIFTYBANK",
            "SENSEX": "SENSEX",
        }
    )

    def ensure_output_dirs(self) -> None:
        for name in ("intermediate", "reports"):
            (self.outputs_dir / name).mkdir(parents=True, exist_ok=True)

    @property
    def report_prefix(self) -> str:
        return self.strategy

    @property
    def persistence_bars(self) -> int:
        return self.persistence_bars_1m if self.bar_freq == "1min" else self.persistence_bars_5m

    @property
    def max_holding_bars(self) -> int:
        return self.holding_bars_1m if self.bar_freq == "1min" else self.holding_bars_5m

    @property
    def zscore_window(self) -> int:
        return self.zscore_window_1m if self.bar_freq == "1min" else self.zscore_window_5m
