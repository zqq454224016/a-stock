"""日 K 合并单元测试。"""

import pandas as pd

from quant_system.pipeline.kline_merge import merge_spot_into_daily_kline


def _kline(end: str = "2026-06-30", n: int = 5):
    dates = pd.date_range(end=end, periods=n)
    return pd.DataFrame({
        "date": dates,
        "open": [10.0] * n,
        "high": [11.0] * n,
        "low": [9.0] * n,
        "close": [10.5] * n,
        "volume": [1000.0] * n,
        "code": ["600378"] * n,
    })


def test_merge_spot_appends_missing_day():
    df = _kline("2026-06-30")
    spot = {
        "close": 12.0, "open": 11.0, "high": 12.5, "low": 10.8,
        "volume": 2000.0, "amount_yi": 1.5,
    }
    merged, meta = merge_spot_into_daily_kline(df, spot, target_date="2026-07-01")
    assert len(merged) == 6
    assert merged.iloc[-1]["close"] == 12.0
    assert meta["kline_merged"] is True
    assert meta["kline_merge_action"] == "append"
    assert meta["kline_stale"] is False


def test_merge_spot_updates_same_day():
    df = _kline("2026-07-01")
    spot = {"close": 13.0, "open": 12.0, "high": 13.5, "low": 11.5, "volume": 3000.0}
    merged, meta = merge_spot_into_daily_kline(df, spot, target_date="2026-07-01")
    assert len(merged) == 5
    assert merged.iloc[-1]["close"] == 13.0
    assert meta["kline_merge_action"] == "update"


def test_merge_spot_marks_stale_without_spot():
    df = _kline("2026-06-30")
    merged, meta = merge_spot_into_daily_kline(df, None, target_date="2026-07-01")
    assert len(merged) == 5
    assert meta["kline_stale"] is True
    assert meta["kline_merged"] is False
