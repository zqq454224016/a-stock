"""数据校验。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    pass


def validate_market_snapshot(data: dict[str, Any]) -> None:
    """校验大盘快照完整性。"""
    required = ["trade_date", "indices", "top_gainers", "top_losers"]
    missing = [k for k in required if k not in data or not data[k]]
    if missing:
        raise ValidationError(f"大盘快照缺少关键字段: {missing}")
    if len(data["indices"]) < 2:
        logger.warning("指数数量过少: %s", len(data["indices"]))


def validate_kline_df(df: pd.DataFrame, min_rows: int = 20) -> None:
    if df is None or len(df) < min_rows:
        raise ValidationError(f"K线数据不足: {len(df) if df is not None else 0} < {min_rows}")
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValidationError(f"K线缺少列: {col}")
