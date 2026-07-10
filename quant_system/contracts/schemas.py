"""模块化算法框架的标准契约对象。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class UniverseMember:
    code: str
    name: str
    trade_date: str = ""
    quality_score: float = 100.0
    market_scope: str = "watchlist"
    is_tradeable: bool = True
    data_version: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Signal:
    code: str
    source: str
    direction: str
    strength: float
    confidence: str = "low"
    horizon: str = ""
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    version: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RiskCheck:
    code: str
    passed: bool
    level: str
    checks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PortfolioTarget:
    code: str
    target_position_pct: float
    action: str
    source: str
    confidence: str = "low"
    reasons: list[str] = field(default_factory=list)
    invalid_conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionIntent:
    code: str
    action: str
    target_position_pct: float
    allowed: bool
    requires_human_review: bool = True
    reason: str = ""
    source: str = "framework"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisFinding:
    code: str
    topic: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FrameworkSnapshot:
    framework_version: str
    updated_at: str
    universe: list[UniverseMember]
    signals: list[Signal]
    risk_checks: list[RiskCheck]
    portfolio_targets: list[PortfolioTarget]
    execution_intents: list[ExecutionIntent]
    analysis_findings: list[AnalysisFinding]
    coverage: dict[str, Any]
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework_version": self.framework_version,
            "updated_at": self.updated_at,
            "universe": [x.to_dict() for x in self.universe],
            "signals": [x.to_dict() for x in self.signals],
            "risk_checks": [x.to_dict() for x in self.risk_checks],
            "portfolio_targets": [x.to_dict() for x in self.portfolio_targets],
            "execution_intents": [x.to_dict() for x in self.execution_intents],
            "analysis_findings": [x.to_dict() for x in self.analysis_findings],
            "coverage": self.coverage,
            "limitations": self.limitations,
        }
