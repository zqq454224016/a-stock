"""盘中实时分析（分钟线 + 实时价）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.market_session import market_session_label
from quant_system.utils.time_utils import now_str, today_str


def _calc_ma(series: pd.Series, window: int) -> float | None:
    if len(series) < 1:
        return None
    return round(float(series.tail(window).mean()), 2)


def _period_return(closes: pd.Series, bars: int) -> float | None:
    if len(closes) <= bars:
        return None
    base = float(closes.iloc[-1 - bars])
    last = float(closes.iloc[-1])
    return round((last / base - 1) * 100, 2) if base else None


def build_intraday_analysis(
    code: str,
    name: str,
    spot: dict | None,
    minute_1m: pd.DataFrame,
    minute_5m: pd.DataFrame | None = None,
    *,
    minute_trade_date: str = "",
    minute_is_today: bool = False,
) -> dict[str, Any]:
    """基于实时价 + 1 分钟 K 构建盘中分析。"""
    code = normalize_code(code)
    m1 = minute_1m.copy()
    has_spot = spot is not None and spot.get("close") is not None
    quote_source = "spot" if has_spot else "minute"

    if m1.empty and not has_spot:
        return {
            "code": code,
            "name": name or code,
            "symbol": to_symbol(code),
            "trade_date": today_str(),
            "updated_at": now_str(),
            "quote_source": "none",
            "minute_trade_date": minute_trade_date,
            "minute_stale": True,
            "market_session": market_session_label(),
            "quote": {},
            "intraday": {"signal": "无数据", "bars_1m": 0},
            "minute_bars": [],
            "minute_5_bars": [],
        }

    closes = m1["close"].astype(float) if not m1.empty else pd.Series(dtype=float)
    volumes = m1["volume"].astype(float) if "volume" in m1.columns and not m1.empty else pd.Series([0.0])

    if has_spot:
        quote = dict(spot)
        if spot.get("name"):
            name = spot["name"]
    elif not m1.empty:
        last_bar = m1.iloc[-1]
        bar_close = float(last_bar["close"])
        quote = {
            "close": bar_close,
            "change": 0.0,
            "change_pct": 0.0,
            "open": float(last_bar.get("open", bar_close)),
            "high": float(last_bar.get("high", bar_close)),
            "low": float(last_bar.get("low", bar_close)),
            "volume": float(last_bar.get("volume", 0)),
            "amount_yi": round(float(last_bar.get("amount", 0) or 0) / 1e8, 2),
            "name": name or code,
        }
    else:
        quote = {"close": 0, "change": 0, "change_pct": 0, "name": name or code}

    close = float(quote["close"])
    minute_stale = not minute_is_today if minute_trade_date else (not m1.empty and not has_spot)

    # 分钟线非当日：价格用 spot，指标仅参考（或置空）
    if not m1.empty:
        ma5_1m = _calc_ma(closes, 5)
        ma20_1m = _calc_ma(closes, 20)
        ma60_1m = _calc_ma(closes, 60)
        avg_vol = float(volumes.tail(20).mean()) if len(volumes) >= 5 else float(volumes.mean() or 1)
        cur_vol = float(volumes.iloc[-1]) if len(volumes) else 0
        volume_ratio = round(cur_vol / avg_vol, 2) if avg_vol > 0 else None
        change_5m = _period_return(closes, 5) if not minute_stale else None
        change_15m = _period_return(closes, 15) if not minute_stale else None
    else:
        ma5_1m = ma20_1m = ma60_1m = volume_ratio = change_5m = change_15m = None

    signal = "震荡"
    if minute_stale and has_spot:
        pct = float(quote.get("change_pct") or 0)
        if pct > 1:
            signal = "强势"
        elif pct < -1:
            signal = "弱势"
    elif ma5_1m and ma20_1m:
        if close >= ma5_1m >= ma20_1m and (change_5m or 0) > 0:
            signal = "强势"
        elif close < ma5_1m <= ma20_1m and (change_5m or 0) < 0:
            signal = "弱势"

    minute_bars = []
    if not m1.empty:
        tail = m1.tail(120)
        for _, r in tail.iterrows():
            minute_bars.append({
                "time": r["datetime"].strftime("%H:%M"),
                "datetime": r["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(float(r["open"]), 2),
                "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2),
                "close": round(float(r["close"]), 2),
                "volume": round(float(r.get("volume", 0) or 0), 0),
            })

    minute_5_bars = []
    if minute_5m is not None and not minute_5m.empty and not minute_stale:
        for _, r in minute_5m.tail(48).iterrows():
            minute_5_bars.append({
                "time": r["datetime"].strftime("%H:%M"),
                "close": round(float(r["close"]), 2),
                "volume": round(float(r.get("volume", 0) or 0), 0),
            })

    return {
        "code": code,
        "name": name,
        "symbol": to_symbol(code),
        "trade_date": today_str(),
        "updated_at": now_str(),
        "quote_source": quote_source,
        "minute_trade_date": minute_trade_date or (minute_bars[-1]["datetime"][:10] if minute_bars else ""),
        "minute_stale": minute_stale,
        "market_session": market_session_label(),
        "quote": quote,
        "intraday": {
            "signal": signal,
            "ma5_1m": ma5_1m,
            "ma20_1m": ma20_1m,
            "ma60_1m": ma60_1m,
            "above_ma5": close >= ma5_1m if ma5_1m else None,
            "above_ma20": close >= ma20_1m if ma20_1m else None,
            "volume_ratio": volume_ratio,
            "change_5m": change_5m,
            "change_15m": change_15m,
            "bars_1m": len(m1),
        },
        "minute_bars": minute_bars,
        "minute_5_bars": minute_5_bars,
    }
