from __future__ import annotations

import re

import pandas as pd

NUMERIC_PATTERNS = [
    r"^(bp|sp|bq|sq|bo|so)\d+$",
    r"^(lp|ltq|v|ap|pc|oi|poi|toi|tbq|tsq|o|h|l|c|uc|lc|ue|le|52h|52l|pp|ml|ts|ls|ti)$",
]


def _is_numeric_col(column: str) -> bool:
    return any(re.fullmatch(pattern, column) for pattern in NUMERIC_PATTERNS)


def normalize_market_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col == "timestamp":
            out[col] = pd.to_datetime(out[col], errors="coerce", utc=False)
            if out[col].dt.tz is None:
                out[col] = out[col].dt.tz_localize("Asia/Kolkata")
        elif col == "ft":
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
        elif _is_numeric_col(col):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = out[col]
    return out
