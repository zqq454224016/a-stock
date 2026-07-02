"""A 股交易规则：T+1、涨跌停、停牌。"""

from __future__ import annotations

import pandas as pd

from quant_system.config.backtest_config import BacktestConfig


def is_suspended(row: pd.Series) -> bool:
    vol = float(row.get("volume", 0) or 0)
    return vol <= 0


def is_limit_up(open_price: float, prev_close: float, cfg: BacktestConfig) -> bool:
    if prev_close <= 0:
        return False
    return open_price >= prev_close * (1 + cfg.limit_pct) * 0.999


def is_limit_down(open_price: float, prev_close: float, cfg: BacktestConfig) -> bool:
    if prev_close <= 0:
        return False
    return open_price <= prev_close * (1 - cfg.limit_pct) * 1.001


def round_lot(shares: float, lot: int) -> int:
    return int(shares // lot) * lot
