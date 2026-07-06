"""选股解释 Agent（P4-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.config.agent_config import SCORE_BEARISH, SCORE_BULLISH


def explain_stock_selection(ctx: StockContext) -> dict[str, Any]:
    factors = (ctx.factors or {}).get("factors") or {}
    signal = ctx.signal or {}
    sentiment = (ctx.sentiment or {}).get("factors") or {}
    stock = ctx.stock or {}
    analysis = stock.get("analysis") or {}

    score = factors.get("multi_factor_score")
    if score is None:
        score = signal.get("signal_score", 50)

    evidence: list[str] = []
    drivers: list[str] = []
    risks: list[str] = []

    if factors.get("technical_score") is not None:
        evidence.append(f"技术分 {factors['technical_score']}")
    if factors.get("sentiment_score") is not None:
        evidence.append(f"情绪分 {factors['sentiment_score']}")
    if factors.get("fundamental_score") is not None:
        evidence.append(f"基本面分 {factors['fundamental_score']}")
    if factors.get("fund_flow_score") is not None:
        evidence.append(f"资金分 {factors['fund_flow_score']}")

    if signal.get("signal"):
        drivers.extend(signal.get("drivers") or [])
        risks.extend(signal.get("limitations") or [])
    if analysis.get("trend"):
        evidence.append(f"趋势 {analysis['trend']}")
    if sentiment.get("label"):
        evidence.append(f"舆情 {sentiment['label']}")

    pe = (factors.get("fundamental_detail") or {}).get("pe_ttm")
    if pe is not None and float(pe) > 60:
        risks.append("估值偏高")

    if score >= SCORE_BULLISH:
        verdict = "positive"
        headline = "综合因子偏多，可纳入观察池"
    elif score <= SCORE_BEARISH:
        verdict = "negative"
        headline = "综合因子偏空，谨慎对待"
    else:
        verdict = "neutral"
        headline = "综合因子中性，等待更清晰信号"

    return {
        "verdict": verdict,
        "headline": headline,
        "composite_score": score,
        "evidence": evidence,
        "drivers": drivers or ["暂无明确驱动"],
        "risks": risks or ["无额外风险标记"],
        "primary_signal": signal.get("signal"),
        "trend": analysis.get("trend"),
    }
