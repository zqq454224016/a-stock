"""复权处理（P0）。"""

from __future__ import annotations

import pandas as pd

from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def apply_adjustment(df: pd.DataFrame, adj_type: str = "qfq") -> pd.DataFrame:
    """
    复权说明：
    - 数据源（新浪 daily / 腾讯 hist_tx）已支持 adjust 参数，返回前复权/后复权数据
    - 本函数用于二次校验与标记，以及未来自算复权的扩展点
    """
    df = df.copy()
    if adj_type not in ("qfq", "hfq", "none"):
        raise ValueError(f"不支持的复权类型: {adj_type}")

    df["adj_type"] = adj_type

    # 校验 OHLC 一致性
    invalid = (df["high"] < df["low"]) | (df["high"] < df["open"]) | (df["high"] < df["close"])
    if invalid.any():
        n = int(invalid.sum())
        logger.warning("复权校验：剔除 %s 条 OHLC 异常记录", n)
        df = df[~invalid]

    return df


def calc_ma(df: pd.DataFrame, windows: tuple[int, ...] = (5, 10, 20, 60)) -> pd.DataFrame:
    df = df.copy()
    for w in windows:
        df[f"ma{w}"] = df["close"].rolling(w, min_periods=1).mean()
    return df
