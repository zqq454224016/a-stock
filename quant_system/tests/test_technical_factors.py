"""技术因子单元测试。"""

import pandas as pd

from quant_system.factors.technical import compute_technical_factors


def _sample_df(n: int = 90) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [10.0 + (i % 7 - 3) * 0.1 + i * 0.02 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 0.2 for c in closes],
        "low": [c - 0.2 for c in closes],
        "close": closes,
        "volume": [100000.0 + i * 1000 for i in range(n)],
    })


def test_compute_technical_factors():
    df = _sample_df()
    result = compute_technical_factors(
        df, "600378", trade_date="2026-03-20", data_version="daily_kline_600378_20260320",
    )
    assert result["code"] == "600378"
    assert result["factor_version"] == "1.0.0"
    assert result["data_version"] == "daily_kline_600378_20260320"
    assert "factors" in result
    f = result["factors"]
    assert f["rsi14"] is not None
    assert f["ma20_bias"] is not None
    assert f["macd"] is not None
    assert f["ma_cross"] in ("golden", "death", "none")


def test_close_override():
    df = _sample_df()
    last_close = float(df.iloc[-1]["close"])
    result = compute_technical_factors(
        df, "600378", trade_date="2026-03-20", close_override=last_close * 1.1,
    )
    assert result["factors"]["ma20_bias"] is not None
