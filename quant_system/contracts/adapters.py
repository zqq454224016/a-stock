"""把现有模块输出适配为标准算法契约。"""

from __future__ import annotations

from typing import Any

from quant_system.contracts.schemas import (
    AnalysisFinding,
    ExecutionIntent,
    FrameworkSnapshot,
    PortfolioTarget,
    RiskCheck,
    Signal,
    UniverseMember,
)
from quant_system.utils.time_utils import now_str

FRAMEWORK_VERSION = "1.0.0"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _direction_from_selector(status: str) -> str:
    return {
        "candidate": "up",
        "watch": "neutral",
        "weak": "neutral",
        "rejected": "down",
    }.get(status, "neutral")


def _strength_from_prediction(prediction: dict[str, Any]) -> float:
    probability = _f(prediction.get("probability"), 0.5)
    direction = prediction.get("direction", "neutral")
    if direction == "down":
        return round((1 - probability) * 100, 2)
    if direction == "neutral":
        return round(min(probability, 0.52) * 100, 2)
    return round(probability * 100, 2)


def _universe_member(code: str, stock: dict[str, Any]) -> UniverseMember:
    quality = stock.get("quality") or {}
    qscore = _f(quality.get("quality_score"), 100.0)
    return UniverseMember(
        code=code,
        name=stock.get("name") or code,
        trade_date=stock.get("trade_date") or "",
        quality_score=qscore,
        is_tradeable=qscore >= 70,
        data_version=stock.get("data_version"),
        notes=[] if qscore >= 70 else ["数据质量低于70分，仅作参考"],
    )


def _prediction_signal(code: str, prediction: dict[str, Any]) -> Signal | None:
    if not prediction:
        return None
    return Signal(
        code=code,
        source="prediction",
        direction=prediction.get("direction", "neutral"),
        strength=_strength_from_prediction(prediction),
        confidence=prediction.get("confidence", "low"),
        horizon=prediction.get("horizon", ""),
        evidence=[
            f"预测概率 {_f(prediction.get('probability'), 0.5):.2f}",
            f"期望收益 {_f(prediction.get('expected_return')):.4f}",
        ] + list(prediction.get("drivers") or []),
        risks=list(prediction.get("risk_flags") or []),
        version=prediction.get("prediction_version", ""),
        updated_at=prediction.get("updated_at", ""),
    )


def _selector_signal(code: str, selector: dict[str, Any]) -> Signal | None:
    if not selector:
        return None
    return Signal(
        code=code,
        source="selector",
        direction=_direction_from_selector(selector.get("status", "weak")),
        strength=_f(selector.get("upside_score")),
        confidence="medium" if selector.get("status") in ("candidate", "watch") else "low",
        horizon="1-5d",
        evidence=list(selector.get("reasons") or []),
        risks=list((selector.get("risks") or []) + (selector.get("reject_reasons") or [])),
        version=selector.get("selector_version", ""),
        updated_at=selector.get("updated_at", ""),
    )


def _recommendation_signals(code: str, recommendations: dict[str, Any]) -> list[Signal]:
    signals: list[Signal] = []
    for period_key, period in (recommendations.get("periods") or {}).items():
        for item in period.get("evaluated") or []:
            if item.get("code") != code:
                continue
            status = item.get("status")
            signals.append(Signal(
                code=code,
                source=f"recommendation.{period_key}",
                direction="up" if status == "recommended" else "neutral" if status == "watch" else "down",
                strength=_f(item.get("score")),
                confidence="medium" if status in ("recommended", "watch") else "low",
                horizon=item.get("horizon", ""),
                evidence=list(item.get("evidence") or []),
                risks=list(item.get("risks") or []),
                version=recommendations.get("recommendation_version", ""),
                updated_at=recommendations.get("updated_at", ""),
            ))
    return signals


def _risk_check(code: str, stock: dict[str, Any], selector: dict[str, Any], decision: dict[str, Any]) -> RiskCheck:
    blockers: list[str] = []
    warnings: list[str] = []
    quality_score = _f((stock.get("quality") or {}).get("quality_score"), 100)
    if quality_score < 70:
        blockers.append("数据质量低于70分")
    blockers.extend(selector.get("reject_reasons") or [])
    if decision.get("action") in ("sell", "reduce"):
        warnings.append(f"决策动作为{decision.get('action')}")
    warnings.extend(decision.get("risks") or [])
    passed = not blockers
    level = "block" if blockers else "warn" if warnings else "pass"
    return RiskCheck(
        code=code,
        passed=passed,
        level=level,
        checks=["数据质量", "候选池排除项", "操作建议风险"],
        blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
    )


def _portfolio_target(code: str, decision: dict[str, Any]) -> PortfolioTarget | None:
    if not decision:
        return None
    return PortfolioTarget(
        code=code,
        target_position_pct=round(_f(decision.get("position_suggestion")), 4),
        action=decision.get("action", "watch"),
        source="decision",
        confidence=decision.get("confidence", "low"),
        reasons=list(decision.get("reasons") or []),
        invalid_conditions=list(decision.get("invalid_conditions") or []),
    )


def _execution_intent(code: str, target: PortfolioTarget | None, risk: RiskCheck) -> ExecutionIntent:
    if not target:
        return ExecutionIntent(
            code=code,
            action="watch",
            target_position_pct=0.0,
            allowed=False,
            reason="缺少标准目标仓位",
        )
    allowed = risk.passed and target.action in ("buy", "hold", "reduce", "sell")
    return ExecutionIntent(
        code=code,
        action=target.action,
        target_position_pct=target.target_position_pct,
        allowed=allowed,
        requires_human_review=target.action in ("buy", "reduce", "sell"),
        reason="通过风险门禁，可进入人工确认" if allowed else "风险门禁未通过或仅观察",
        source=target.source,
    )


def _analysis_findings(code: str, replay: dict[str, Any], impact: dict[str, Any]) -> list[AnalysisFinding]:
    findings: list[AnalysisFinding] = []
    summary = replay.get("summary") or {}
    if summary:
        findings.append(AnalysisFinding(
            code=code,
            topic="十日推演",
            summary=f"命中率 {_f(summary.get('hit_rate')) * 100:.0f}%",
            evidence=[f"{k}: {v}" for k, v in summary.items()],
            limitations=list(replay.get("limitations") or []),
            source="replay",
        ))
    if impact:
        findings.append(AnalysisFinding(
            code=code,
            topic="实际影响",
            summary=f"方向 {impact.get('impact_direction', 'neutral')}，评分 {_f(impact.get('impact_score')):.0f}",
            evidence=[
                f"{e.get('event_type')}: {e.get('title')}"
                for e in (impact.get("events") or [])[:5]
                if e.get("title")
            ],
            limitations=list(impact.get("limitations") or []),
            source="impact",
        ))
    return findings


def _coverage(codes: list[str], inputs: dict[str, dict[str, Any]], signals: list[Signal]) -> dict[str, Any]:
    total = len(codes)
    modules = {
        name: sum(1 for code in codes if payloads.get(code))
        for name, payloads in inputs.items()
    }
    return {
        "universe_count": total,
        "signal_count": len(signals),
        "module_coverage": {
            name: {
                "count": count,
                "ratio": round(count / total, 4) if total else 0.0,
            }
            for name, count in modules.items()
        },
    }


def build_framework_snapshot(
    *,
    stocks: dict[str, dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    selectors: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    impacts: dict[str, dict[str, Any]],
    replays: dict[str, dict[str, Any]],
    recommendations: dict[str, Any],
) -> dict[str, Any]:
    codes = sorted(set(stocks) | set(predictions) | set(selectors) | set(decisions))
    universe: list[UniverseMember] = []
    signals: list[Signal] = []
    risks: list[RiskCheck] = []
    targets: list[PortfolioTarget] = []
    intents: list[ExecutionIntent] = []
    findings: list[AnalysisFinding] = []

    for code in codes:
        stock = stocks.get(code) or {"name": code}
        universe.append(_universe_member(code, stock))
        for signal in (
            _prediction_signal(code, predictions.get(code) or {}),
            _selector_signal(code, selectors.get(code) or {}),
        ):
            if signal:
                signals.append(signal)
        signals.extend(_recommendation_signals(code, recommendations))

        risk = _risk_check(code, stock, selectors.get(code) or {}, decisions.get(code) or {})
        risks.append(risk)
        target = _portfolio_target(code, decisions.get(code) or {})
        if target:
            targets.append(target)
        intents.append(_execution_intent(code, target, risk))
        findings.extend(_analysis_findings(code, replays.get(code) or {}, impacts.get(code) or {}))

    snapshot = FrameworkSnapshot(
        framework_version=FRAMEWORK_VERSION,
        updated_at=now_str(),
        universe=universe,
        signals=signals,
        risk_checks=risks,
        portfolio_targets=targets,
        execution_intents=intents,
        analysis_findings=findings,
        coverage=_coverage(codes, {
            "stocks": stocks,
            "predictions": predictions,
            "selectors": selectors,
            "decisions": decisions,
            "impacts": impacts,
            "replays": replays,
        }, signals),
        limitations=[
            "当前为现有 JSON 输出的标准契约适配层，尚未替换各模块内部算法。",
            "执行意图只表示可进入人工确认，不代表自动下单。",
            "实盘辅助已按用户要求跳过，账户与委托契约仍待后续接入。",
        ],
    )
    return snapshot.to_dict()
