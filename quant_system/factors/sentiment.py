"""舆情情绪因子（多空比、热度、加速度）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.sentiment_config import (
    DESIRE_BEAR,
    DESIRE_BULL,
    FOCUS_ACCEL_THRESHOLD,
    SENTIMENT_VERSION,
)
from quant_system.utils.time_utils import now_str


def _label_from_desire(desire: float | None, accel: float | None) -> str:
    if desire is None:
        return "中性"
    if desire >= DESIRE_BULL or (accel is not None and accel >= FOCUS_ACCEL_THRESHOLD and desire > 50):
        return "看多"
    if desire <= DESIRE_BEAR or (accel is not None and accel <= -FOCUS_ACCEL_THRESHOLD and desire < 50):
        return "看空"
    return "中性"


def compute_sentiment_factors(raw: dict[str, Any]) -> dict[str, Any]:
    """从舆情原始数据计算 Quantification.md §3.1 指标。"""
    em = raw.get("em_snapshot") or {}
    series = raw.get("em_series") or {}
    desire_rows = series.get("desire") or []
    focus_rows = series.get("focus") or []

    latest_desire = None
    desire_change = None
    if desire_rows:
        last = desire_rows[-1]
        latest_desire = float(last.get("参与意愿", 0) or 0)
        desire_change = float(last.get("参与意愿变化", 0) or 0)

    focus_index = float(em.get("focus_index", 0) or 0)
    focus_accel = None
    if len(focus_rows) >= 2:
        focus_accel = float(focus_rows[-1].get("用户关注指数", 0) or 0) - float(
            focus_rows[-2].get("用户关注指数", 0) or 0
        )

    long_short_ratio = round(latest_desire / max(100 - latest_desire, 1), 4) if latest_desire else None
    heat_index = round(focus_index, 2) if focus_index else None
    sentiment_accel = round(focus_accel, 2) if focus_accel is not None else None

    xq = raw.get("xueqiu_hot") or {}
    xq_heat = max(xq.get("tweet_heat", 0), xq.get("follow_heat", 0), xq.get("deal_heat", 0))

    label = _label_from_desire(latest_desire, sentiment_accel)

    limitations = ["not_backtested", "sentiment_proxy"]
    if not desire_rows:
        limitations.append("em_desire_missing")
    if not any(xq.get(k) for k in ("in_hot_tweet", "in_hot_follow", "in_hot_deal")):
        limitations.append("xueqiu_not_in_hot")

    return {
        "code": raw.get("code"),
        "trade_date": raw.get("trade_date"),
        "sentiment_version": SENTIMENT_VERSION,
        "platform": "eastmoney+xueqiu",
        "label": label,
        "long_short_ratio": long_short_ratio,
        "heat_index": heat_index,
        "sentiment_accel": sentiment_accel,
        "desire_score": latest_desire,
        "desire_change": desire_change,
        "composite_score": em.get("composite_score"),
        "rank_change": em.get("rank_change"),
        "xueqiu_hot": xq,
        "xueqiu_heat": xq_heat,
        "post_count": len(raw.get("posts") or []),
        "limitations": limitations,
        "updated_at": now_str(),
    }
