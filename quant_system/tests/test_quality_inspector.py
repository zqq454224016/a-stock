"""质量巡检单元测试。"""

import pandas as pd

from quant_system.pipeline.quality_inspector import find_missing_trade_dates, inspect_kline_df
from quant_system.utils.trade_calendar import TradeCalendar


class _MockCalendar(TradeCalendar):
    def fetch_dates(self, force_refresh: bool = False) -> list[str]:
        return [
            "2026-01-02", "2026-01-03", "2026-01-06", "2026-01-07",
            "2026-01-08", "2026-01-09", "2026-01-10",
        ]

    def latest_trade_day(self, on_or_before=None) -> str:
        return "2026-01-10"


def _sample_kline(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": [10.0] * len(dates),
        "high": [11.0] * len(dates),
        "low": [9.0] * len(dates),
        "close": [10.5] * len(dates),
        "volume": [1000.0] * len(dates),
    })


def test_find_missing_trade_dates():
    cal = _MockCalendar()
    df = _sample_kline(["2026-01-02", "2026-01-03", "2026-01-07", "2026-01-09"])
    missing = find_missing_trade_dates(df, "2026-01-02", "2026-01-10", cal)
    assert "2026-01-06" in missing
    assert "2026-01-08" in missing


def test_inspect_kline_df_warning():
    cal = _MockCalendar()
    df = _sample_kline(["2026-01-02", "2026-01-03", "2026-01-07"])
    report = inspect_kline_df("600378", df, calendar=cal, lookback_days=30)
    assert report["status"] in ("warning", "error")
    assert report["code"] == "600378"
    assert "quality_score" in report
    assert report["quality_score"] < 90
