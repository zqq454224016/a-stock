"""初级走势信号单元测试。"""

from quant_system.factors.signal import compute_primary_signal


def test_primary_signal_bullish():
    factors = {
        "above_ma20": True,
        "ma_cross": "golden",
        "rsi14": 62,
        "macd_hist": 0.5,
        "momentum_20": 8,
        "volume_ratio_20": 1.5,
        "ma20_bias": 5,
    }
    out = compute_primary_signal(factors, "600378", "2026-07-01")
    assert out["signal"] == "bullish"
    assert out["signal_score"] >= 60
    assert "not_backtested" in out["limitations"]
    assert "ma_golden_cross" in out["drivers"]


def test_primary_signal_bearish():
    factors = {
        "above_ma20": False,
        "ma_cross": "death",
        "rsi14": 35,
        "macd_hist": -0.3,
        "momentum_20": -10,
        "ma20_bias": -5,
    }
    out = compute_primary_signal(factors, "600378", "2026-07-01")
    assert out["signal"] == "bearish"
    assert out["signal_score"] <= 40
