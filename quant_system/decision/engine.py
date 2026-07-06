"""单股指导性操作决策引擎。"""

from __future__ import annotations

from typing import Any

from quant_system.config.decision_config import DECISION_VERSION, DecisionConfig
from quant_system.utils.time_utils import now_str


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _position_for(code: str, account: dict[str, Any] | None) -> dict[str, Any]:
    return ((account or {}).get("positions") or {}).get(code, {})


def _factor_score(factors_payload: dict[str, Any] | None) -> float:
    factors = (factors_payload or {}).get("factors") or {}
    for key in ("multi_factor_score", "technical_score"):
        if factors.get(key) is not None:
            return _to_float(factors.get(key), 50.0)
    return 50.0


def _backtest_health(backtest: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not backtest:
        return "missing", ["缺少回测证据"]
    metrics = backtest.get("metrics") or {}
    win_rate = _to_float(metrics.get("win_rate_pct"), 0.0)
    sharpe = _to_float(metrics.get("sharpe_ratio"), 0.0)
    max_dd = _to_float(metrics.get("max_drawdown_pct"), 0.0)
    risks: list[str] = []
    if win_rate < 35:
        risks.append(f"回测胜率偏低 {win_rate}%")
    if sharpe < 0.3:
        risks.append(f"夏普偏低 {sharpe}")
    if max_dd <= -40:
        risks.append(f"历史最大回撤较大 {max_dd}%")
    if len(risks) >= 2:
        return "weak", risks
    if risks:
        return "mixed", risks
    return "ok", ["回测指标处于可接受区间"]


def _position_status(position: dict[str, Any]) -> tuple[int, float]:
    shares = int(position.get("shares") or 0)
    pnl_pct = _to_float(position.get("unrealized_pnl_pct"), 0.0)
    return shares, pnl_pct


def _target_for_bullish(probability: float, confidence: str, factor_score: float, cfg: DecisionConfig) -> float:
    if probability >= cfg.strong_buy_probability and factor_score >= cfg.strong_factor_score and confidence == "high":
        return cfg.max_position_pct
    if confidence in ("high", "medium"):
        return cfg.medium_position_pct
    return cfg.starter_position_pct


def build_stock_decision(
    *,
    code: str,
    name: str = "",
    trade_date: str = "",
    stock: dict[str, Any] | None = None,
    prediction: dict[str, Any] | None = None,
    factors: dict[str, Any] | None = None,
    backtest: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    agent_report: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
    cfg: DecisionConfig | None = None,
) -> dict[str, Any]:
    """合成单股指导性操作建议。"""
    cfg = cfg or DecisionConfig()
    prediction = prediction or {}
    quality = quality or {}
    stock = stock or {}
    agent_report = agent_report or {}
    impact = impact or {}

    qscore = _to_float(quality.get("quality_score") or (stock.get("quality") or {}).get("quality_score"), 100.0)
    factor_score = _factor_score(factors)
    direction = prediction.get("direction", "neutral")
    probability = _to_float(prediction.get("probability"), 0.5)
    confidence = prediction.get("confidence", "low")
    risk_flags = list(prediction.get("risk_flags") or [])
    impact_score = _to_float(impact.get("impact_score"), 0.0)
    impact_direction = impact.get("impact_direction", "neutral")
    bt_health, bt_notes = _backtest_health(backtest)
    position = _position_for(code, account)
    shares, pnl_pct = _position_status(position)
    has_position = shares > 0

    reasons: list[str] = []
    risks: list[str] = []
    invalid_conditions: list[str] = []
    action = "watch"
    target_pct = 0.0
    confidence_out = "low"

    if qscore < cfg.min_quality_score:
        action = "watch"
        reasons.append(f"数据质量不足，quality_score={qscore}")
        risks.append("low_data_quality")
        invalid_conditions.append("quality_score_below_minimum")
    elif not prediction:
        action = "hold" if has_position else "watch"
        reasons.append("缺少预测结果，暂不新增操作")
        risks.append("missing_prediction")
    else:
        if direction == "up" and probability >= cfg.buy_probability and factor_score >= cfg.min_factor_score and bt_health != "weak":
            target_pct = _target_for_bullish(probability, confidence, factor_score, cfg)
            if impact_direction == "positive" and impact_score >= 20:
                target_pct = min(cfg.max_position_pct, target_pct + 0.03)
                reasons.append(f"实际影响数据偏正面，impact_score={impact_score}")
            if has_position:
                action = "hold"
                reasons.append("预测偏多且已有持仓，维持或调至目标仓位")
            else:
                action = "buy"
                reasons.append("预测偏多，因子与回测未出现强否定")
            confidence_out = "high" if confidence == "high" and bt_health == "ok" else "medium"
        elif has_position and (direction == "down" or probability <= 0.45):
            action = "sell" if confidence == "high" else "reduce"
            target_pct = 0.0 if action == "sell" else min(cfg.starter_position_pct, cfg.max_position_pct / 2)
            reasons.append("预测转弱，已有持仓需降低风险暴露")
            confidence_out = "medium" if confidence == "high" else "low"
        elif has_position:
            action = "hold"
            target_pct = min(cfg.starter_position_pct, cfg.max_position_pct)
            reasons.append("信号不强但已有持仓，维持观察")
            confidence_out = "medium"
        else:
            action = "watch"
            reasons.append("预测、因子或回测条件不足，暂不买入")
            confidence_out = "medium" if direction == "neutral" else "low"

    if impact_direction == "negative" and impact_score <= -20:
        risks.append(f"实际影响数据偏负面，impact_score={impact_score}")
        if action == "buy":
            action = "watch"
            target_pct = 0.0
            invalid_conditions.append("negative_impact_overrides_buy")
        elif action == "hold":
            action = "reduce"
            target_pct = min(target_pct, cfg.starter_position_pct)

    if impact_direction == "positive" and impact_score >= 20 and action == "watch":
        reasons.append(f"存在正面实际影响数据，impact_score={impact_score}，但预测/回测条件未满足")

    if has_position and pnl_pct <= cfg.stop_loss_pct:
        action = "sell"
        target_pct = 0.0
        risks.append(f"触发止损阈值，当前浮盈亏 {pnl_pct}%")
        invalid_conditions.append("stop_loss_triggered")
    elif has_position and pnl_pct >= cfg.take_profit_pct and action in ("hold", "buy"):
        action = "reduce"
        target_pct = min(target_pct, cfg.starter_position_pct)
        reasons.append(f"浮盈 {pnl_pct}% 达到止盈观察区，建议部分落袋")
        invalid_conditions.append("take_profit_zone")

    if risk_flags:
        risks.extend(risk_flags)
    if bt_health in ("weak", "mixed"):
        risks.extend(bt_notes)
    elif bt_notes:
        reasons.extend(bt_notes[:1])

    if action in ("buy", "hold") and target_pct > cfg.max_position_pct:
        target_pct = cfg.max_position_pct

    if action in ("watch", "sell"):
        target_pct = 0.0

    evidence = {
        "prediction": {
            "direction": direction,
            "probability": probability,
            "confidence": confidence,
            "expected_return": prediction.get("expected_return"),
            "risk_flags": risk_flags,
        },
        "factor_score": factor_score,
        "quality_score": qscore,
        "backtest_health": bt_health,
        "position": {
            "shares": shares,
            "unrealized_pnl_pct": pnl_pct,
            "market_value": position.get("market_value"),
        },
        "agent_summary": agent_report.get("summary"),
        "impact": {
            "impact_score": impact_score,
            "impact_direction": impact_direction,
            "events": [
                {
                    "event_type": e.get("event_type"),
                    "title": e.get("title"),
                    "impact_score": e.get("impact_score"),
                    "impact_direction": e.get("impact_direction"),
                }
                for e in (impact.get("events") or [])[:5]
            ],
            "limitations": impact.get("limitations") or [],
        },
    }

    return {
        "code": code,
        "name": name or stock.get("name") or code,
        "trade_date": trade_date or stock.get("trade_date") or prediction.get("trade_date") or "",
        "decision_version": DECISION_VERSION,
        "action": action,
        "position_suggestion": round(target_pct, 4),
        "confidence": confidence_out,
        "reasons": list(dict.fromkeys(reasons)) or ["暂无明确理由"],
        "risks": list(dict.fromkeys(risks)) or ["无额外风险标记"],
        "invalid_conditions": list(dict.fromkeys(invalid_conditions)),
        "evidence": evidence,
        "requires_human_review": action in ("buy", "reduce", "sell"),
        "disclaimer": "指导性意见，仅供研究和模拟交易，不构成投资建议",
        "updated_at": now_str(),
    }
