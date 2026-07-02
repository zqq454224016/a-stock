"""初级走势信号（技术因子倾向，未经回测验证）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.factor_config import PRIMARY_SIGNAL_VERSION
from quant_system.utils.time_utils import now_str


def compute_primary_signal(
    factors: dict[str, Any],
    code: str,
    trade_date: str,
    horizon: str = "5d",
) -> dict[str, Any]:
    """基于技术因子生成 bullish / bearish / neutral 初级信号。"""
    score = 50.0
    drivers: list[str] = []

    if factors.get("above_ma20"):
        score += 10
        drivers.append("above_ma20")

    ma_cross = factors.get("ma_cross")
    if ma_cross == "golden":
        score += 15
        drivers.append("ma_golden_cross")
    elif ma_cross == "death":
        score -= 15
        drivers.append("ma_death_cross")

    rsi = factors.get("rsi14")
    if rsi is not None:
        if rsi >= 60:
            score += 8
            drivers.append("rsi14_strong")
        elif rsi <= 40:
            score -= 8
            drivers.append("rsi14_weak")
        elif rsi >= 50:
            score += 4
            drivers.append("rsi14_neutral_up")

    macd_hist = factors.get("macd_hist")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 6
            drivers.append("macd_hist_positive")
        else:
            score -= 6
            drivers.append("macd_hist_negative")

    momentum = factors.get("momentum_20")
    if momentum is not None:
        if momentum > 5:
            score += 8
            drivers.append("momentum_20_up")
        elif momentum < -5:
            score -= 8
            drivers.append("momentum_20_down")

    vol_ratio = factors.get("volume_ratio_20")
    if vol_ratio is not None and vol_ratio >= 1.2:
        score += 5
        drivers.append("volume_expansion")

    bias = factors.get("ma20_bias")
    if bias is not None and bias > 3:
        score += 5
        drivers.append("ma20_breakout")
    elif bias is not None and bias < -3:
        score -= 5
        drivers.append("ma20_breakdown")

    score = max(0.0, min(100.0, round(score, 1)))
    if score >= 60:
        signal = "bullish"
    elif score <= 40:
        signal = "bearish"
    else:
        signal = "neutral"

    return {
        "code": code,
        "trade_date": trade_date,
        "horizon": horizon,
        "signal": signal,
        "signal_score": score,
        "drivers": drivers,
        "limitations": ["not_backtested", "technical_only"],
        "signal_version": PRIMARY_SIGNAL_VERSION,
        "updated_at": now_str(),
    }
