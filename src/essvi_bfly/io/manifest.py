from __future__ import annotations

from pathlib import Path

import pandas as pd

from essvi_bfly.instruments import load_manifest


def load_manifest_with_paths(path: str | Path) -> pd.DataFrame:
    df = load_manifest(path)
    df["absolute_path"] = df["absolute_path"].astype(str)
    return df
