"""标准化算法契约层。"""

from quant_system.contracts.adapters import build_framework_snapshot
from quant_system.contracts.schemas import (
    AnalysisFinding,
    ExecutionIntent,
    FrameworkSnapshot,
    PortfolioTarget,
    RiskCheck,
    Signal,
    UniverseMember,
)

__all__ = [
    "AnalysisFinding",
    "ExecutionIntent",
    "FrameworkSnapshot",
    "PortfolioTarget",
    "RiskCheck",
    "Signal",
    "UniverseMember",
    "build_framework_snapshot",
]
