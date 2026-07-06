"""动态股票池与流动性过滤（P2-4）。"""

from __future__ import annotations

import pandas as pd

from quant_system.config.backtest_config import BacktestConfig


def is_st_name(name: str) -> bool:
    n = (name or "").upper().replace("*", "")
    return "ST" in n


def check_stock_eligible(name: str, cfg: BacktestConfig) -> tuple[bool, str | None]:
    if cfg.exclude_st and is_st_name(name):
        return False, "st_excluded"
    return True, None


def _daily_amount(row: pd.Series) -> float:
    if "amount" in row.index and pd.notna(row.get("amount")):
        return float(row["amount"] or 0)
    vol = float(row.get("volume", 0) or 0)
    close = float(row.get("close", 0) or 0)
    return vol * close


def prepare_backtest_df(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """标记可交易日（停牌 / 流动性不足）。"""
    work = df.copy()
    min_amount = cfg.min_daily_amount_yi * 1e8
    amounts = work.apply(_daily_amount, axis=1)
    work["tradable"] = (work["volume"].astype(float) > 0) & (amounts >= min_amount)
    work["daily_amount_yi"] = (amounts / 1e8).round(4)
    return work
