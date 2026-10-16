"""Deterministic analysis of the latest available trading day's price changes."""

from __future__ import annotations

from collections import Counter
from statistics import mean, median
from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def change_bucket(change_pct: float) -> str:
    if change_pct >= 9.8:
        return "limit_up"
    if change_pct >= 5:
        return "strong_up"
    if change_pct > 0:
        return "up"
    if change_pct == 0:
        return "flat"
    if change_pct <= -9.8:
        return "limit_down"
    if change_pct <= -5:
        return "strong_down"
    return "down"


def analyze_stock_change(stock: dict[str, Any], benchmark_change_pct: float = 0.0) -> dict[str, Any]:
    quote = stock.get("quote") or {}
    bars = stock.get("kline") or []
    close = _number(quote.get("close"))
    open_price = _number(quote.get("open"))
    high = _number(quote.get("high"))
    low = _number(quote.get("low"))
    change_pct = _number(quote.get("change_pct"))
    previous_close = _number(bars[-2].get("close")) if len(bars) >= 2 else 0.0
    if previous_close > 0 and close > 0:
        calculated = (close / previous_close - 1) * 100
        if quote.get("change_pct") is None:
            change_pct = calculated
    gap_pct = (open_price / previous_close - 1) * 100 if previous_close > 0 and open_price > 0 else 0.0
    intraday_pct = (close / open_price - 1) * 100 if open_price > 0 and close > 0 else 0.0
    amplitude_pct = (high - low) / previous_close * 100 if previous_close > 0 and high >= low else 0.0
    prior_volumes = [_number(row.get("volume")) for row in bars[-6:-1] if _number(row.get("volume")) > 0]
    volume = _number(quote.get("volume") or (bars[-1].get("volume") if bars else 0))
    volume_ratio = volume / mean(prior_volumes) if prior_volumes and volume > 0 else None
    relative_strength = change_pct - benchmark_change_pct

    drivers: list[str] = []
    if gap_pct >= 1:
        drivers.append("高开贡献明显")
    elif gap_pct <= -1:
        drivers.append("低开形成压力")
    if intraday_pct >= 1:
        drivers.append("开盘后资金继续推升")
    elif intraday_pct <= -1:
        drivers.append("开盘后持续走弱")
    if volume_ratio is not None and volume_ratio >= 1.5:
        drivers.append("成交量显著放大")
    elif volume_ratio is not None and volume_ratio <= 0.7:
        drivers.append("成交量偏低")
    if relative_strength >= 1:
        drivers.append("明显跑赢市场")
    elif relative_strength <= -1:
        drivers.append("明显跑输市场")
    if not drivers:
        drivers.append("涨跌主要处于市场正常波动范围")

    return {
        "code": stock.get("code"),
        "name": stock.get("name"),
        "trade_date": stock.get("trade_date"),
        "close": round(close, 4),
        "change_pct": round(change_pct, 2),
        "bucket": change_bucket(change_pct),
        "gap_pct": round(gap_pct, 2),
        "intraday_pct": round(intraday_pct, 2),
        "amplitude_pct": round(amplitude_pct, 2),
        "volume_ratio_5d": round(volume_ratio, 2) if volume_ratio is not None else None,
        "benchmark_change_pct": round(benchmark_change_pct, 2),
        "relative_strength_pct": round(relative_strength, 2),
        "drivers": drivers,
        "limitations": ["仅为价格量能归因，不能证明真实因果"] if bars else ["缺少日线，无法计算开盘贡献和量比"],
    }


def summarize_today(
    rows: list[dict[str, Any]],
    *,
    trade_date: str,
    indices: list[dict[str, Any]] | None = None,
    industries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    changes = [_number(row.get("change_pct")) for row in rows]
    buckets = Counter(str(row.get("bucket") or "unknown") for row in rows)
    advances = sum(1 for value in changes if value > 0)
    declines = sum(1 for value in changes if value < 0)
    flats = len(changes) - advances - declines
    breadth = advances / (advances + declines) if advances + declines else 0.0
    if breadth >= 0.65:
        mood = "普涨"
    elif breadth >= 0.52:
        mood = "偏强"
    elif breadth >= 0.45:
        mood = "分化"
    elif breadth >= 0.35:
        mood = "偏弱"
    else:
        mood = "普跌"
    ordered = sorted(rows, key=lambda row: _number(row.get("change_pct")), reverse=True)
    industry_rows = sorted(
        industries or [], key=lambda row: _number(row.get("change_pct")), reverse=True,
    )
    return {
        "trade_date": trade_date,
        "sample_count": len(rows),
        "breadth": {
            "advances": advances,
            "declines": declines,
            "flats": flats,
            "advance_ratio": round(breadth, 4),
            "advance_decline_ratio": round(advances / declines, 2) if declines else None,
        },
        "distribution": dict(buckets),
        "average_change_pct": round(mean(changes), 2) if changes else None,
        "median_change_pct": round(median(changes), 2) if changes else None,
        "market_state": mood,
        "indices": indices or [],
        "leading_industries": industry_rows[:5],
        "lagging_industries": list(reversed(industry_rows[-5:])),
        "top_gainers": ordered[:10],
        "top_losers": list(reversed(ordered[-10:])),
        "limitations": [
            "今日指最近一个可用交易日，不等同于自然日",
            "涨跌归因为价格量能特征解释，不代表已确认的新闻或资金因果",
        ],
    }
