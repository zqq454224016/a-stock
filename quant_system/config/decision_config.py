"""单股决策配置（指导性意见 MVP）。"""

from __future__ import annotations

from dataclasses import dataclass

DECISION_VERSION = "1.0.0"


@dataclass
class DecisionConfig:
    min_quality_score: float = 70.0
    good_quality_score: float = 90.0
    buy_probability: float = 0.58
    strong_buy_probability: float = 0.65
    min_factor_score: float = 55.0
    strong_factor_score: float = 70.0
    max_position_pct: float = 0.20
    starter_position_pct: float = 0.08
    medium_position_pct: float = 0.12
    stop_loss_pct: float = -8.0
    take_profit_pct: float = 20.0
