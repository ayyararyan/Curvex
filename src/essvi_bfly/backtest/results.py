from __future__ import annotations

from pathlib import Path

import pandas as pd


def write_results(base_dir: Path, reports: dict[str, pd.DataFrame], prefix: str = "") -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in reports.items():
        filename = f"{prefix}_{name}.csv" if prefix else f"{name}.csv"
        path = base_dir / filename
        frame.to_csv(path, index=False)
