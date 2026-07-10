"""Agent 输入输出标准结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from quant_system.config.agent_config import AGENT_REPORT_SCHEMA_VERSION


@dataclass(slots=True)
class EvidencePackage:
    code: str
    name: str
    trade_date: str
    task: str
    allowed_actions: list[str]
    stock: dict[str, Any] | None = None
    factors: dict[str, Any] | None = None
    signal: dict[str, Any] | None = None
    prediction: dict[str, Any] | None = None
    backtest: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    sentiment: dict[str, Any] | None = None
    enhance: dict[str, Any] | None = None
    impact: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    framework: dict[str, Any] | None = None
    missing_inputs: list[str] = field(default_factory=list)
    inputs_used: list[str] = field(default_factory=list)
    schema_version: str = AGENT_REPORT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentProviderResult:
    provider: str
    model: str
    prompt_version: str
    summary: str
    direction_view: str
    confidence: str
    evidence: list[str]
    risks: list[str]
    failure_conditions: list[str]
    suggested_actions: list[str]
    forbidden_actions: list[str] = field(default_factory=list)
    requires_human_review: bool = True
    raw_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_evidence_package(ctx: Any, *, strategy: str = "ma_cross", task: str = "stock_review") -> EvidencePackage:
    """从现有 StockContext 构建只读证据包。"""
    stock = ctx.stock
    factors = ctx.factors
    signal = ctx.signal
    prediction = ctx.prediction
    backtest = ctx.backtest(strategy)
    quality = ctx.quality
    sentiment = ctx.sentiment
    enhance = ctx.enhance
    impact = ctx.impact
    decision = ctx.decision
    framework = ctx._read("framework/snapshot.json")

    inputs = {
        "stock": stock,
        "factors": factors,
        "signal": signal,
        "prediction": prediction,
        "backtest": backtest,
        "quality": quality,
        "sentiment": sentiment,
        "enhance": enhance,
        "impact": impact,
        "decision": decision,
        "framework": framework,
    }
    return EvidencePackage(
        code=ctx.code,
        name=ctx.name,
        trade_date=ctx.trade_date,
        task=task,
        allowed_actions=["analyze", "summarize", "suggest"],
        stock=stock,
        factors=factors,
        signal=signal,
        prediction=prediction,
        backtest=backtest,
        quality=quality,
        sentiment=sentiment,
        enhance=enhance,
        impact=impact,
        decision=decision,
        framework=framework,
        missing_inputs=[name for name, value in inputs.items() if not value],
        inputs_used=sorted(set(ctx.inputs_used)),
    )
