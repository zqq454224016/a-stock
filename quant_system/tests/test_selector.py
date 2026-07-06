"""上涨候选池测试。"""

from quant_system.selector.builder import build_upside_candidate


def test_selector_marks_strong_upside_candidate():
    row = build_upside_candidate(
        code="600001",
        name="测试股票",
        stock={
            "trade_date": "2026-07-06",
            "analysis": {
                "ma_signal": {"above_ma20": True, "above_ma60": True},
                "returns": {"d5": 4, "d20": 12},
            },
        },
        prediction={"direction": "up", "probability": 0.66, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 72, "macd_hist": 1.2, "above_ma20": True}},
        backtest={"metrics": {"sharpe_ratio": 1.2, "max_drawdown_pct": -18, "win_rate_pct": 55}},
        quality={"quality_score": 98},
        impact={"impact_score": 25, "impact_direction": "positive"},
    )

    assert row["status"] == "candidate"
    assert row["upside_score"] >= 70
    assert not row["reject_reasons"]


def test_selector_rejects_down_prediction_even_with_positive_impact():
    row = build_upside_candidate(
        code="600002",
        prediction={"direction": "down", "probability": 0.35, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 70}},
        backtest={"metrics": {"sharpe_ratio": 1.5, "max_drawdown_pct": -12, "win_rate_pct": 60}},
        quality={"quality_score": 98},
        impact={"impact_score": 35, "impact_direction": "positive"},
    )

    assert row["status"] == "rejected"
    assert "预测方向为 down" in row["reject_reasons"]
