"""多因子合成（技术 + 情绪 + 基本面 + 资金）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.factor_config import (
    COMPOSITE_FACTOR_VERSION,
    WEIGHT_FUNDAMENTAL,
    WEIGHT_FUND_FLOW,
    WEIGHT_SENTIMENT,
    WEIGHT_TECHNICAL,
)
from quant_system.factors.fundamental import compute_enhance_factors
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


def _blend_multi_factor(
    tech_score: float,
    sent_score: float | None,
    fund_score: float | None,
    flow_score: float | None,
) -> tuple[float, dict[str, float]]:
    parts: list[tuple[str, float, float]] = [("technical", tech_score, WEIGHT_TECHNICAL)]
    if sent_score is not None:
        parts.append(("sentiment", sent_score, WEIGHT_SENTIMENT))
    if fund_score is not None:
        parts.append(("fundamental", fund_score, WEIGHT_FUNDAMENTAL))
    if flow_score is not None:
        parts.append(("fund_flow", flow_score, WEIGHT_FUND_FLOW))

    total_w = sum(w for _, _, w in parts)
    multi = sum(s * w / total_w for _, s, w in parts)
    weights_used = {name: round(w / total_w, 3) for name, _, w in parts}
    return round(multi, 1), weights_used


def build_composite_factors(
    code: str,
    trade_date: str,
    technical: dict[str, Any],
    *,
    sentiment: dict[str, Any] | None = None,
    enhance: dict[str, Any] | None = None,
    data_version: str | None = None,
    technical_version: str = "1.0.0",
    sentiment_version: str | None = None,
    enhance_version: str | None = None,
) -> dict[str, Any]:
    """合并技术/情绪/基本面/资金因子。"""
    tech_score = round(_technical_score(technical), 1)
    sent_score = _sentiment_score(sentiment)
    enhance_factors = compute_enhance_factors(enhance)
    fund_score = enhance_factors.get("fundamental_score")
    flow_score = enhance_factors.get("fund_flow_score")

    multi, weights_used = _blend_multi_factor(tech_score, sent_score, fund_score, flow_score)

    merged = {
        **technical,
        "technical_score": tech_score,
        "sentiment_score": sent_score,
        "fundamental_score": fund_score,
        "fund_flow_score": flow_score,
        "multi_factor_score": multi,
        "has_sentiment": sent_score is not None,
        "has_fundamental": fund_score is not None,
        "has_fund_flow": flow_score is not None,
        "factor_weights": weights_used,
        "fundamental_detail": enhance_factors.get("fundamental_detail"),
        "fund_flow_detail": enhance_factors.get("fund_flow_detail"),
    }

    return {
        "code": code,
        "trade_date": trade_date,
        "factor_version": COMPOSITE_FACTOR_VERSION,
        "technical_version": technical_version,
        "sentiment_version": sentiment_version,
        "enhance_version": enhance_version or enhance_factors.get("enhance_version"),
        "data_version": data_version,
        "factors": merged,
        "updated_at": now_str(),
    }
