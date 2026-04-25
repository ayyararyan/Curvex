from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


@dataclass(slots=True)
class ParsedContract:
    contract_name: str
    root_symbol: str
    instrument_type: str
    option_side: str | None
    strike: float | None
    expiry_code: str | None


def load_contract_inventory(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    if "strike" in df.columns:
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    return df


def load_manifest(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    if "strike" in df.columns:
        df["strike"] = pd.to_numeric(df["strike"], errors="coerce")
    manifest_path = Path(path)
    repo_root = manifest_path.resolve().parents[2]
    raw_root = repo_root / "data" / "raw" / "january_2026"
    if "relative_path" in df.columns:
        df["resolved_path"] = df["relative_path"].map(lambda rel: str(raw_root / rel) if rel else "")
    else:
        df["resolved_path"] = df.get("absolute_path", "")
    return df


def parse_contract_name(contract_name: str) -> ParsedContract:
    if contract_name in {"NIFTY50", "NIFTYBANK", "SENSEX"}:
        return ParsedContract(contract_name, contract_name, "INDEX", None, None, None)
    option_match = re.fullmatch(r"([A-Z]+)(\d{2}[A-Z]{3}|\d{5})(\d+)(CE|PE)", contract_name)
    if option_match:
        root_symbol, expiry_code, strike, option_side = option_match.groups()
        return ParsedContract(contract_name, root_symbol, "OPT", option_side, float(strike), expiry_code)
    fut_match = re.fullmatch(r"([A-Z]+)(\d{2}[A-Z]{3})FUT", contract_name)
    if fut_match:
        root_symbol, expiry_code = fut_match.groups()
        return ParsedContract(contract_name, root_symbol, "FUT", None, None, expiry_code)
    raise ValueError(f"Unrecognized contract name: {contract_name}")


def build_session_file_map(
    manifest: pd.DataFrame,
    session_date: str,
    root_symbol: str,
    expiry_code: str | None = None,
) -> pd.DataFrame:
    mask = (manifest["session_date"] == session_date) & (manifest["root_symbol"] == root_symbol)
    if expiry_code is not None:
        mask &= manifest["expiry_code"] == expiry_code
    return manifest.loc[mask].copy()


def last_weekday(year: int, month: int, weekday: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day)
    while dt.weekday() != weekday:
        dt = dt.replace(day=dt.day - 1)
    return dt


def resolve_expiry_datetime(root_symbol: str, expiry_code: str | None) -> pd.Timestamp | None:
    if not expiry_code:
        return None
    if re.fullmatch(r"\d{2}[A-Z]{3}", expiry_code):
        year = 2000 + int(expiry_code[:2])
        month = MONTHS[expiry_code[2:5]]
        dt = last_weekday(year, month, 3)
        return pd.Timestamp(dt.replace(hour=15, minute=30, second=0, microsecond=0, tzinfo=IST))
    if re.fullmatch(r"\d{5}", expiry_code):
        year = 2000 + int(expiry_code[:2])
        month = int(expiry_code[2])
        day = int(expiry_code[3:])
        return pd.Timestamp(datetime(year, month, day, 15, 30, tzinfo=IST))
    raise ValueError(f"Unsupported expiry code: {expiry_code}")


def session_date_to_timestamp(session_date: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.strptime(session_date, "%Y_%m_%d").replace(tzinfo=IST))
