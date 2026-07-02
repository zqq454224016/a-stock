"""走势预测单元测试。"""

import pandas as pd

from quant_system.prediction.verified import build_verified_prediction


def _sample_df(n: int = 200) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    closes = [10.0 + i * 0.03 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.2 for c in closes],
        "close": closes,
        "volume": [100000.0] * n,
    })


def _factors_bullish() -> dict:
    return {
        "above_ma20": True,
        "ma20_bias": 5.0,
        "rsi14": 55.0,
        "macd_hist": 0.1,
        "ma_cross": "golden",
        "atr14": 0.5,
    }


def _backtest_stub() -> dict:
    return {
        "strategy_version": "1.0.0",
        "metrics": {
            "win_rate_pct": 55.0,
            "profit_loss_ratio": 1.2,
            "annual_return_pct": 10.0,
            "max_drawdown_pct": -20.0,
            "closed_trades": 30,
        },
    }


def test_build_verified_prediction_structure():
    pred = build_verified_prediction(
        "600378", _sample_df(), _factors_bullish(),
        backtest=_backtest_stub(), horizon="5d",
        data_version="test_v1",
    )
    assert pred["code"] == "600378"
    assert pred["horizon"] == "5d"
    assert pred["direction"] in ("up", "down", "neutral")
    assert 0 <= pred["probability"] <= 1
    assert pred["confidence"] in ("low", "medium", "high")
    assert "evidence" in pred
    assert pred["evidence"]["sample_count"] > 0
    assert "disclaimer" in pred


def test_prediction_no_certainty_wording():
    pred = build_verified_prediction(
        "600378", _sample_df(), _factors_bullish(), backtest=_backtest_stub(),
    )
    text = str(pred)
    assert "必涨" not in text and "必跌" not in text
