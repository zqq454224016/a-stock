"""跨源校验单元测试。"""

import pandas as pd

from quant_system.pipeline.cross_source import compare_daily_close


def _df(dates, closes):
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "close": closes,
        "open": closes,
        "high": closes,
        "low": closes,
        "volume": [1000.0] * len(dates),
    })


def test_compare_daily_close_ok():
    dates = ["2026-06-25", "2026-06-26", "2026-06-27"]
    primary = _df(dates, [10.0, 10.1, 10.2])
    alt = _df(dates, [10.0, 10.11, 10.19])
    result = compare_daily_close(primary, alt, lookback=5)
    assert result["compared_days"] == 3
    assert result["status"] == "ok"
    assert result["cross_source_diff"] is not None
    assert result["cross_source_diff"] < 0.01


def test_compare_daily_close_warning():
    dates = ["2026-06-25", "2026-06-26"]
    primary = _df(dates, [10.0, 10.0])
    alt = _df(dates, [10.0, 10.2])
    result = compare_daily_close(primary, alt, lookback=5, warn_pct=0.5)
    assert result["status"] in ("warning", "error")
    assert result["max_diff_pct"] == 2.0
