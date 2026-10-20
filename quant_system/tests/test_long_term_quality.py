import gzip
import json

import pandas as pd

from quant_system.strategy.long_term_quality import (
    attach_point_in_time_quality,
    exit_on_quality_break,
    known_date,
    quality_gate,
)


def test_known_date_caps_late_source_dates_at_statutory_deadline():
    # 数据源把旧季报的披露日写成一年后，法定截止日更早
    record = {"report_period": "2021-03-31", "known_at": "2022-04-27T23:59:59+08:00"}
    assert str(known_date(record)) == "2021-04-30"
    record = {"report_period": "2025-12-31", "known_at": "2026-03-20T23:59:59+08:00"}
    assert str(known_date(record)) == "2026-03-20"


def test_quality_join_only_uses_reports_known_before_each_day(tmp_path):
    root = tmp_path / "point_in_time_financials" / "by_code"
    root.mkdir(parents=True)
    good = {"revenue_yoy_pct": 5, "net_profit_yoy_pct": 5, "operating_cashflow_per_share": 1, "roe_pct": 3}
    records = [
        {"report_period": "2025-03-31", "known_at": "2025-04-25", "metrics": good},
        {"report_period": "2025-06-30", "known_at": "2025-08-20", "metrics": {**good, "roe_pct": -1}},
    ]
    with gzip.open(root / "600001.json.gz", "wt", encoding="utf-8") as stream:
        json.dump(records, stream)
    days = pd.DataFrame({"date": ["2025-04-24", "2025-05-10", "2025-08-19", "2025-08-21"]})
    out = attach_point_in_time_quality(days, tmp_path, "600001")
    assert out["fundamental_quality_known"].tolist() == [False, True, True, True]
    assert out["fundamental_quality_pass"].tolist() == [False, True, True, False]


def test_quality_gate_fails_closed_on_missing_point_in_time_fields():
    result = quality_gate({"revenue_growth": 1.0})
    assert result["passed"] is False
    assert "profit_growth" in result["missing"]


def test_quality_gate_requires_cashflow_and_debt_discipline():
    good = quality_gate({"revenue_growth": 0.1, "profit_growth": 0.2, "operating_cash_flow": 10, "debt_to_assets": 0.4})
    bad = quality_gate({"revenue_growth": 0.1, "profit_growth": 0.2, "operating_cash_flow": -1, "debt_to_assets": 0.8})
    assert good["passed"] is True
    assert bad["passed"] is False


def test_quality_exit_requires_confirmed_multi_dimension_deterioration():
    prev = {"revenue_growth": .2, "profit_growth": .3, "operating_cash_flow": 10, "debt_to_assets": .4}
    current = {"revenue_growth": -.1, "profit_growth": -.2, "operating_cash_flow": -5, "debt_to_assets": .5}
    assert exit_on_quality_break(prev, current)["exit"] is True
