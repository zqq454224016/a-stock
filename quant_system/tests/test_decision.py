"""单股决策引擎测试。"""

from quant_system.decision.engine import build_stock_decision


def test_decision_buy_when_prediction_and_factors_confirm():
    d = build_stock_decision(
        code="600378",
        name="昊华科技",
        prediction={"direction": "up", "probability": 0.66, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 75}},
        backtest={"metrics": {"win_rate_pct": 55, "sharpe_ratio": 1.0, "max_drawdown_pct": -15}},
        quality={"quality_score": 98},
        account={"positions": {}},
    )
    assert d["action"] == "buy"
    assert d["position_suggestion"] == 0.2
    assert d["requires_human_review"] is True


def test_decision_watch_when_quality_is_low():
    d = build_stock_decision(
        code="600378",
        prediction={"direction": "up", "probability": 0.8, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 90}},
        backtest={"metrics": {"win_rate_pct": 60, "sharpe_ratio": 1.2, "max_drawdown_pct": -10}},
        quality={"quality_score": 50},
    )
    assert d["action"] == "watch"
    assert "quality_score_below_minimum" in d["invalid_conditions"]


def test_decision_sell_existing_position_on_bearish_prediction():
    d = build_stock_decision(
        code="600378",
        prediction={"direction": "down", "probability": 0.4, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 45}},
        backtest={"metrics": {"win_rate_pct": 45, "sharpe_ratio": 0.8, "max_drawdown_pct": -20}},
        quality={"quality_score": 95},
        account={"positions": {"600378": {"shares": 100, "unrealized_pnl_pct": 3.0}}},
    )
    assert d["action"] == "sell"
    assert d["position_suggestion"] == 0.0


def test_decision_stop_loss_overrides_hold():
    d = build_stock_decision(
        code="600378",
        prediction={"direction": "up", "probability": 0.7, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 80}},
        backtest={"metrics": {"win_rate_pct": 55, "sharpe_ratio": 1.0, "max_drawdown_pct": -20}},
        quality={"quality_score": 95},
        account={"positions": {"600378": {"shares": 100, "unrealized_pnl_pct": -9.0}}},
    )
    assert d["action"] == "sell"
    assert "stop_loss_triggered" in d["invalid_conditions"]
