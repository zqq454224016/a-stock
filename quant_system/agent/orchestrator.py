"""Agent 编排。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.agent.predict_review import review_prediction
from quant_system.agent.stock_explainer import explain_stock_selection
from quant_system.agent.strategy_diagnosis import diagnose_strategy
from quant_system.config.agent_config import AGENT_DISCLAIMER, AGENT_VERSION
from quant_system.utils.time_utils import now_str


def _data_health(ctx: StockContext) -> dict[str, Any]:
    q = ctx.quality or {}
    stock = ctx.stock or {}
    quality = stock.get("quality") or {}
    score = q.get("quality_score") or quality.get("quality_score")
    return {
        "status": q.get("status") or quality.get("status", "unknown"),
        "quality_score": score,
        "factor_eligible": q.get("factor_eligible", quality.get("factor_eligible")),
        "issues": q.get("issues") or quality.get("issues") or [],
    }


def _overall_summary(selection: dict, diagnosis: dict, review: dict) -> tuple[str, str]:
    verdict = selection.get("verdict", "neutral")
    diag = diagnosis.get("verdict", "unknown")
    align = review.get("alignment", "unknown")

    if verdict == "negative" or diag == "weak":
        return "谨慎", "low"
    if verdict == "positive" and diag in ("ok", "mixed") and align in ("aligned", "partial", "unknown"):
        return selection.get("headline", "偏多观察"), "medium"
    if align == "divergent":
        return "信号分歧，宜观望", "low"
    return selection.get("headline", "中性观察"), "medium"


def build_agent_report(ctx: StockContext, *, strategy: str = "ma_cross") -> dict[str, Any]:
    selection = explain_stock_selection(ctx)
    diagnosis = diagnose_strategy(ctx, strategy=strategy)
    review = review_prediction(ctx)
    health = _data_health(ctx)
    summary, confidence = _overall_summary(selection, diagnosis, review)

    limitations = ["rule_based_only", "no_auto_trade"]
    if not ctx.prediction:
        limitations.append("prediction_missing")
    if not diagnosis.get("available"):
        limitations.append("backtest_missing")

    return {
        "code": ctx.code,
        "name": ctx.name,
        "trade_date": ctx.trade_date,
        "version": AGENT_VERSION,
        "updated_at": now_str(),
        "summary": summary,
        "confidence": confidence,
        "disclaimer": AGENT_DISCLAIMER,
        "stock_selection": selection,
        "strategy_diagnosis": diagnosis,
        "prediction_review": review,
        "data_health": health,
        "limitations": limitations,
        "audit": {
            "inputs_used": sorted(set(ctx.inputs_used)),
            "strategy_ref": strategy,
        },
    }
