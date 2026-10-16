import pandas as pd

from quant_system.pipeline.quality_inspector import inspect_kline_df


class Calendar:
    def latest_trade_day(self):
        return "2026-07-03"

    def trade_days_between(self, start, end):
        return ["2026-07-01", "2026-07-02", "2026-07-03"]


def test_expected_suspension_does_not_reduce_quality():
    frame = pd.DataFrame([
        {"date": "2026-07-01", "close": 10, "volume": 100},
        {"date": "2026-07-03", "close": 10, "volume": 100},
    ])
    result = inspect_kline_df(
        "600001", frame, calendar=Calendar(),
        allowed_missing_dates={"2026-07-02"},
    )
    assert result["missing_dates"] == []
    assert result["explained_suspension_dates"] == ["2026-07-02"]
    assert result["quality_score"] == 100
    assert result["factor_eligible"] is True
