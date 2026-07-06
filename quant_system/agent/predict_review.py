"""预测复盘 Agent（P4-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext


def _dir_cn(d: str | None) -> str:
    return {"up": "偏多", "down": "偏空", "neutral": "震荡", "bullish": "偏多", "bearish": "偏空"}.get(d or "", d or "—")


def review_prediction(ctx: StockContext) -> dict[str, Any]:
    pred = ctx.prediction
    if not pred:
        return {
            "available": False,
            "notes": ["缺少预测结果，请先运行 predict"],
            "failure_conditions": [],
        }

    signal = ctx.signal or {}
    factors = (ctx.factors or {}).get("factors") or {}
    evidence = pred.get("evidence") or {}

    pred_dir = pred.get("direction")
    sig = signal.get("signal")
    notes: list[str] = []
    failure_conditions: list[str] = []

    notes.append(
        f"{pred.get('horizon', '5d')} 预测 {_dir_cn(pred_dir)}，"
        f"概率 {(pred.get('probability') or 0) * 100:.1f}%，置信度 {pred.get('confidence', '—')}"
    )
    notes.append(f"历史样本 {evidence.get('sample_count', '—')}，回测胜率 {((evidence.get('backtest_win_rate') or 0) * 100):.1f}%")

    sig_map = {"bullish": "up", "bearish": "down", "neutral": "neutral"}
    sig_dir = sig_map.get(sig, sig)
    if sig_dir and pred_dir:
        if sig_dir == pred_dir:
            alignment = "aligned"
            notes.append("初级技术信号与预测方向一致")
        elif sig_dir == "neutral" or pred_dir == "neutral":
            alignment = "partial"
            notes.append("信号与预测部分一致，存在中性分歧")
        else:
            alignment = "divergent"
            notes.append("初级技术信号与预测方向分歧，需人工复核")
            failure_conditions.append("signal_prediction_divergence")
    else:
        alignment = "unknown"

    mfs = factors.get("multi_factor_score")
    if mfs is not None:
        if pred_dir == "up" and mfs < 50:
            failure_conditions.append("low_factor_score_vs_bullish_pred")
            notes.append(f"多因子分 {mfs} 与看多预测不完全匹配")
        elif pred_dir == "down" and mfs > 60:
            failure_conditions.append("high_factor_score_vs_bearish_pred")
            notes.append(f"多因子分 {mfs} 与看空预测不完全匹配")

    for flag in pred.get("risk_flags") or []:
        failure_conditions.append(flag)
        notes.append(f"风险标记: {flag}")

    if evidence.get("backtest_max_drawdown_pct") is not None:
        mdd = float(evidence["backtest_max_drawdown_pct"])
        if mdd <= -40:
            failure_conditions.append("high_historical_drawdown")
            notes.append(f"策略历史回撤 {mdd}% 偏高")

    return {
        "available": True,
        "horizon": pred.get("horizon"),
        "direction": pred_dir,
        "probability": pred.get("probability"),
        "confidence": pred.get("confidence"),
        "expected_return": pred.get("expected_return"),
        "alignment": alignment,
        "drivers": pred.get("drivers") or [],
        "notes": notes,
        "failure_conditions": list(dict.fromkeys(failure_conditions)),
        "disclaimer": pred.get("disclaimer"),
    }
