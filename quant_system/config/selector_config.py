"""上涨候选池筛选配置。"""

from __future__ import annotations

from dataclasses import dataclass

SELECTOR_VERSION = "1.1.0"


@dataclass
class SelectorConfig:
    min_quality_score: float = 70.0
    reject_factor_score: float = 45.0
    watch_factor_score: float = 55.0
    candidate_score: float = 70.0
    watch_score: float = 55.0
    max_acceptable_drawdown_pct: float = -35.0
    min_sharpe: float = 0.8
    positive_impact_score: float = 15.0
    negative_impact_score: float = -20.0
