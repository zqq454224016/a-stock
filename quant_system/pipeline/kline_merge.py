"""日 K 与实时行情合并（解决新浪日 K 滞后）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.utils.trade_calendar import TradeCalendar, get_calendar


def merge_spot_into_daily_kline(
    df: pd.DataFrame,
    spot: dict | None,
    target_date: str | None = None,
    calendar: TradeCalendar | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """用实时快照补全或更新最近交易日 K 线。

    当历史日 K 末根落后于最近交易日、或当日盘中需刷新 OHLCV 时，
    从 spot 合成/更新一根 bar，使图表与现价对齐。
    """
    cal = calendar or get_calendar()
    target = target_date or cal.latest_trade_day()
    meta: dict[str, Any] = {
        "kline_merged": False,
        "kline_merge_action": None,
        "kline_stale": False,
        "kline_target_date": target,
    }

    if df is None or df.empty:
        meta["kline_stale"] = True
        return df, meta

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    last_date = df["date"].iloc[-1]
    target_dt = pd.to_datetime(target)
    meta["kline_stale"] = last_date.strftime("%Y-%m-%d") < target

    if not spot or not spot.get("close"):
        return df, meta

    close = float(spot["close"])
    amount_yi = spot.get("amount_yi")
    amount = float(amount_yi) * 1e8 if amount_yi is not None else float(spot.get("amount", 0) or 0)

    def _spot_bar(dt: pd.Timestamp) -> dict[str, Any]:
        row: dict[str, Any] = {
            "date": dt,
            "open": float(spot.get("open") or close),
            "high": float(spot.get("high") or close),
            "low": float(spot.get("low") or close),
            "close": close,
            "volume": float(spot.get("volume") or 0),
            "amount": amount,
        }
        if "turnover" in df.columns:
            row["turnover"] = float(df["turnover"].iloc[-1] or 0)
        if "code" in df.columns:
            row["code"] = df["code"].iloc[-1]
        if "adj_type" in df.columns:
            row["adj_type"] = df["adj_type"].iloc[-1]
        return row

    if last_date.date() == target_dt.date():
        bar = _spot_bar(target_dt)
        for key, value in bar.items():
            if key in df.columns:
                df.at[df.index[-1], key] = value
        meta["kline_merged"] = True
        meta["kline_merge_action"] = "update"
        meta["kline_stale"] = False
    elif last_date.date() < target_dt.date():
        bar = _spot_bar(target_dt)
        new_row = {col: bar.get(col) for col in df.columns}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        meta["kline_merged"] = True
        meta["kline_merge_action"] = "append"
        meta["kline_stale"] = False

    return df, meta
