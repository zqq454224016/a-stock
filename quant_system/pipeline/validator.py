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
    if data.get("degraded"):
        logger.warning("大盘快照为降级模式: %s", data.get("limitations"))
    if not data.get("trade_date"):
        raise ValidationError("大盘快照缺少 trade_date")
    if not data.get("indices") and not data.get("top_gainers"):
        raise ValidationError("大盘快照缺少指数与涨跌幅数据")
    if len(data.get("indices") or []) < 2:
        logger.warning("指数数量过少: %s", len(data.get("indices") or []))


def validate_kline_df(df: pd.DataFrame, min_rows: int = 20) -> None:
    if df is None or len(df) < min_rows:
        raise ValidationError(f"K线数据不足: {len(df) if df is not None else 0} < {min_rows}")
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValidationError(f"K线缺少列: {col}")
