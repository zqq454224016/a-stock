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
    assert "预测方向为偏空" in row["reject_reasons"]
    assert "预测方向从偏空修复为震荡或偏多" in row["next_triggers"]


def test_selector_boundary_negative_impact_is_risk_not_hard_reject():
    row = build_upside_candidate(
        code="600003",
        stock={
            "analysis": {
                "ma_signal": {"above_ma20": True, "above_ma60": True},
                "returns": {"d5": 2, "d20": 8},
            },
        },
        prediction={"direction": "up", "probability": 0.66, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 72, "macd_hist": 1.0, "above_ma20": True}},
        backtest={"metrics": {"sharpe_ratio": 1.2, "max_drawdown_pct": -18, "win_rate_pct": 55}},
        quality={"quality_score": 98},
        impact={"impact_score": -20, "impact_direction": "negative"},
    )

    assert "实际影响数据显著偏负面" not in row["reject_reasons"]


def test_selector_caps_candidate_to_watch_when_core_confirmation_missing():
    row = build_upside_candidate(
        code="600004",
        stock={
            "analysis": {
                "ma_signal": {"above_ma20": True, "above_ma60": True},
                "returns": {"d5": 2, "d20": 8},
            },
        },
        prediction={"direction": "neutral", "probability": 0.51, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 80, "macd_hist": 1.0, "above_ma20": True}},
        backtest={"metrics": {"sharpe_ratio": 2.0, "max_drawdown_pct": -12, "win_rate_pct": 65}},
        quality={"quality_score": 98},
        impact={"impact_score": 20, "impact_direction": "positive"},
    )

    assert row["status"] == "watch"
    assert "预测尚未形成向上确认" in row["candidate_blockers"]


def test_selector_uses_replay_calibration_when_review_is_pending():
    row = build_upside_candidate(
        code="600005",
        stock={
            "analysis": {
                "ma_signal": {"above_ma20": True, "above_ma60": True},
                "returns": {"d5": 3, "d20": 9},
            },
        },
        prediction={"direction": "up", "probability": 0.56, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 70, "macd_hist": 1.0, "above_ma20": True}},
        backtest={"metrics": {"sharpe_ratio": 1.1, "max_drawdown_pct": -16, "win_rate_pct": 52}},
        quality={"quality_score": 96},
        impact={"impact_score": 10, "impact_direction": "neutral"},
        review={"summary": {"evaluated_count": 0, "hit_rate": None}},
        replay={
            "summary": {"evaluated_count": 10, "hit_rate": 0.2},
            "learning": {"false_up_count": 3, "false_down_count": 1, "miss_reason_distribution": {"概率边界": 2}},
        },
    )

    assert row["calibration"]["mode"] == "replay"
    assert row["metrics"]["candidate_score_threshold"] == 74.0
    assert row["metrics"]["probability_floor"] == 0.58
    assert "预测概率未达到校准确认线 0.58" in row["candidate_blockers"]


def test_selector_prefers_review_calibration_when_enough_samples():
    row = build_upside_candidate(
        code="600006",
        stock={
            "analysis": {
                "ma_signal": {"above_ma20": True, "above_ma60": True},
                "returns": {"d5": 3, "d20": 9},
            },
        },
        prediction={"direction": "up", "probability": 0.62, "confidence": "high"},
        factors={"factors": {"multi_factor_score": 70, "macd_hist": 1.0, "above_ma20": True}},
        backtest={"metrics": {"sharpe_ratio": 1.1, "max_drawdown_pct": -16, "win_rate_pct": 52}},
        quality={"quality_score": 96},
        impact={"impact_score": 10, "impact_direction": "neutral"},
        review={"summary": {"evaluated_count": 5, "hit_rate": 0.8, "avg_return_pct": 2.1}},
        replay={"summary": {"evaluated_count": 10, "hit_rate": 0.2}},
    )

    assert row["calibration"]["mode"] == "review"
    assert row["metrics"]["candidate_score_threshold"] == 68.0
