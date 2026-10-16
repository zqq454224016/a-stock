from __future__ import annotations

import pandas as pd

from quant_system.strategy.trend_development import analyze_trend_development, evaluate_one_year
from quant_system.tasks.strategy_job import validation_calibration


def _frame(count: int = 320, rising: bool = True) -> pd.DataFrame:
    close = [10 + index * (0.05 if rising else -0.02) for index in range(count)]
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=count, freq="B"),
        "open": close, "high": [x * 1.01 for x in close], "low": [x * 0.99 for x in close],
        "close": close, "volume": [1_000_000 + index * 100 for index in range(count)],
    })


def test_trend_strategy_reports_stage_and_manual_review():
    payload = analyze_trend_development(_frame(), "600001", "测试股份")

    assert payload["status"] == "analyzed"
    assert payload["trend_stage"] == "rising"
    assert payload["outlook"]["20d"]["direction"] == "up"
    assert payload["manual_review"]["required"] is True
    assert payload["manual_review"]["status"] == "pending"


def test_one_year_validation_has_multiple_horizons():
    result = evaluate_one_year(_frame())

    assert result["window"] == "past_252_trading_days"
    assert set(result["metrics"]) == {"5d", "20d", "60d"}
    assert result["metrics"]["20d"]["sample_count"] > 100
    assert result["metrics"]["20d"]["hit_rate"] == 1.0


def test_one_year_validation_adapts_to_calibration_contract():
    adapted = validation_calibration({"metrics": {"20d": {
        "sample_count": 180, "hit_rate": 0.62, "avg_signed_return_pct": 2.1,
    }}})

    assert adapted["window_days"] == 252
    assert adapted["summary"]["evaluated_count"] == 180
    assert adapted["summary"]["hit_rate"] == 0.62
