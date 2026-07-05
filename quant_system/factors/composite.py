"""多因子合成（技术 + 情绪）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.factor_config import COMPOSITE_FACTOR_VERSION
from quant_system.utils.time_utils import now_str


def _technical_score(factors: dict[str, Any]) -> float:
    score = 50.0
    if factors.get("above_ma20"):
        score += 10
    cross = factors.get("ma_cross")
    if cross == "golden":
        score += 15
    elif cross == "death":
        score -= 15
    rsi = factors.get("rsi14")
    if rsi is not None:
        if rsi >= 60:
            score += 8
        elif rsi <= 40:
            score -= 8
    hist = factors.get("macd_hist")
    if hist is not None:
        score += 6 if hist > 0 else -6
    mom = factors.get("momentum_20")
    if mom is not None:
        if mom > 5:
            score += 8
        elif mom < -5:
            score -= 8
    vol = factors.get("volume_ratio_20")
    if vol is not None and vol >= 1.2:
        score += 5
    bias = factors.get("ma20_bias")
    if bias is not None and bias > 3:
        score += 5
    elif bias is not None and bias < -3:
        score -= 5
    return max(0.0, min(100.0, score))


def _sentiment_score(sentiment: dict[str, Any] | None) -> float | None:
    if not sentiment:
        return None
    if "long_short_ratio" in sentiment or "desire_score" in sentiment:
        factors = sentiment
    else:
        factors = sentiment.get("factors", {})
    if not factors:
        return None
    score = 50.0
    desire = factors.get("desire_score")
    if desire is not None:
        score += (float(desire) - 50) * 0.6
    heat = factors.get("heat_index")
    if heat is not None:
        score += (float(heat) - 50) * 0.2
    accel = factors.get("sentiment_accel")
    if accel is not None:
        score += float(accel) * 3
    label = factors.get("label")
    if label == "看多":
        score += 5
    elif label == "看空":
        score -= 5
    xq = factors.get("xueqiu_hot") or {}
    if xq.get("in_hot_tweet"):
        score += 3
    return max(0.0, min(100.0, round(score, 1)))


def build_composite_factors(
    code: str,
    trade_date: str,
    technical: dict[str, Any],
    *,
    sentiment: dict[str, Any] | None = None,
    data_version: str | None = None,
    technical_version: str = "1.0.0",
    sentiment_version: str | None = None,
) -> dict[str, Any]:
    """合并技术因子与情绪因子，输出 Quantification.md §4.5 结构。"""
    tech_score = round(_technical_score(technical), 1)
    sent_score = _sentiment_score(sentiment)

    if sent_score is not None:
        multi = round(tech_score * 0.65 + sent_score * 0.35, 1)
        has_sentiment = True
    else:
        multi = tech_score
        has_sentiment = False

    merged = {
        **technical,
        "technical_score": tech_score,
        "sentiment_score": sent_score,
        "multi_factor_score": multi,
        "has_sentiment": has_sentiment,
    }

    return {
        "code": code,
        "trade_date": trade_date,
        "factor_version": COMPOSITE_FACTOR_VERSION,
        "technical_version": technical_version,
        "sentiment_version": sentiment_version,
        "data_version": data_version,
        "factors": merged,
        "updated_at": now_str(),
    }
