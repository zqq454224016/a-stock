"""个股分析构建（pipeline 扩展）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from quant_system.pipeline.adjuster import calc_ma
from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.time_utils import today_str


def build_stock_analysis(
    code: str, name: str, df: pd.DataFrame, spot: dict | None = None,
) -> dict[str, Any]:
    df = calc_ma(df)
    latest = df.iloc[-1]
    kline_close = float(latest["close"])
    kline_date = latest["date"].strftime("%Y-%m-%d")

    def period_return(n: int, base_close: float | None = None) -> float | None:
        if len(df) <= n:
            return None
        base = base_close if base_close is not None else float(df.iloc[-1 - n]["close"])
        ref = float(spot["close"]) if spot else kline_close
        return round((ref / base - 1) * 100, 2) if base else None

    high_60 = float(df["high"].max())
    low_60 = float(df["low"].min())

    if spot:
        quote = dict(spot)
        if spot.get("name"):
            name = spot["name"]
        close = float(quote["close"])
        trade_date = today_str()
        quote_source = "spot"
        # 区间位置用实时价
        pos_pct = round((close - low_60) / (high_60 - low_60) * 100, 1) if high_60 > low_60 else 50.0
    else:
        close = kline_close
        trade_date = kline_date
        quote_source = "kline"
        pos_pct = round((close - low_60) / (high_60 - low_60) * 100, 1) if high_60 > low_60 else 50.0
        quote = {
            "close": close,
            "change": round(close - float(df.iloc[-2]["close"]), 2) if len(df) > 1 else 0,
            "change_pct": period_return(1) or 0,
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "volume": float(latest.get("volume", 0) or 0),
            "amount_yi": round(float(latest.get("amount", 0) or 0) / 1e8, 2),
            "name": name,
        }

    kline = [{
        "date": r["date"].strftime("%Y-%m-%d"),
        "open": round(float(r["open"]), 2),
        "high": round(float(r["high"]), 2),
        "low": round(float(r["low"]), 2),
        "close": round(float(r["close"]), 2),
        "volume": round(float(r.get("volume", 0) or 0), 0),
        "ma5": round(float(r["ma5"]), 2),
        "ma10": round(float(r["ma10"]), 2),
        "ma20": round(float(r["ma20"]), 2),
        "ma60": round(float(r["ma60"]), 2),
    } for _, r in df.iterrows()]

    ma = {f"ma{w}": round(float(latest[f"ma{w}"]), 2) for w in (5, 10, 20, 60)}
    ma_signal = {f"above_ma{w}": close >= float(latest[f"ma{w}"]) for w in (5, 10, 20, 60)}

    trend = "震荡"
    if ma_signal["above_ma5"] and ma_signal["above_ma20"] and ma["ma5"] > ma["ma20"]:
        trend = "偏多"
    elif not ma_signal["above_ma5"] and not ma_signal["above_ma20"] and ma["ma5"] < ma["ma20"]:
        trend = "偏空"

    turnover_raw = float(latest.get("turnover", 0) or 0)
    turnover = round(turnover_raw * 100, 2) if turnover_raw < 1 else round(turnover_raw, 2)

    return {
        "code": normalize_code(code),
        "name": name,
        "symbol": to_symbol(code),
        "trade_date": trade_date,
        "kline_date": kline_date,
        "quote_source": quote_source,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "quote": quote,
        "analysis": {
            "trend": trend,
            "returns": {"d5": period_return(5), "d20": period_return(20), "d60": period_return(60)},
            "ma": ma,
            "ma_signal": ma_signal,
            "range_60d": {"high": round(high_60, 2), "low": round(low_60, 2), "position_pct": pos_pct},
            "turnover": turnover,
        },
        "kline": kline,
    }
