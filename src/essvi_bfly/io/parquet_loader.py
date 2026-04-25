from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_parquet(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)
