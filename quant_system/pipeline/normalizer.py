"""数据标准化。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig


def normalize_code(code: str) -> str:
    return str(code).strip().lower().replace("sh", "").replace("sz", "").replace("bj", "")


def to_symbol(code: str) -> str:
    c = normalize_code(code)
    if c.startswith(("6", "5")):
        return f"sh{c}"
    if c.startswith(("8", "4", "9")):
        return f"bj{c}"
    return f"sz{c}"


def detect_market(code: str) -> str:
    c = normalize_code(code)
    if c.startswith("6"):
        return "SH"
    if c.startswith(("0", "3")):
        return "SZ"
    if c.startswith(("8", "4", "9")):
        return "BJ"
    return ""


def normalize_kline_df(df: pd.DataFrame, code: str, days: int = 120) -> pd.DataFrame:
    """统一 K 线列名与类型。"""
    col_map = {
        "日期": "date", "date": "date",
        "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "换手率": "turnover",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "turnover" not in df.columns:
        df["turnover"] = 0.0

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df = df.tail(days).reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume", "amount", "turnover"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["code"] = normalize_code(code)
    return df


def load_watchlist(config: CrawlerConfig | None = None) -> list[dict]:
    cfg = config or CrawlerConfig()
    if not cfg.watchlist_file.exists():
        return []
    data = json.loads(cfg.watchlist_file.read_text(encoding="utf-8"))
    return data.get("stocks", [])
