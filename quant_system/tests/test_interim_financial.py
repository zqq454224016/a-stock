from __future__ import annotations

import json
import gzip
from datetime import date

from quant_system.tasks.interim_financial_job import (
    _period,
    build_interim_reports,
    build_public_quarterly_reports,
    build_point_in_time_financial_index,
    load_financial_as_of,
    _quarter_periods,
)


def test_interim_period_uses_latest_available_half_year():
    from datetime import date

    assert _period(date(2026, 7, 22)) == "20260630"
    assert _period(date(2026, 3, 1)) == "20250630"


def test_build_interim_report_freezes_latest_announced_version(tmp_path):
    raw = {
        "period": "20260630",
        "datasets": {
            "income": [
                {"ts_code": "600001.SH", "ann_date": "20260715", "revenue": 90},
                {"ts_code": "600001.SH", "ann_date": "20260720", "revenue": 100, "n_income_attr_p": 12},
            ],
            "balance_sheet": [{"ts_code": "600001.SH", "ann_date": "20260720", "total_assets": 500}],
            "cash_flow": [{"ts_code": "600001.SH", "ann_date": "20260720", "n_cashflow_act": 15}],
            "indicators": [{"ts_code": "600001.SH", "ann_date": "20260720", "netprofit_yoy": 20, "or_yoy": 10}],
        },
        "errors": {},
    }

    manifest = build_interim_reports(raw, tmp_path)
    report = json.loads((tmp_path / "600001.json").read_text(encoding="utf-8"))

    assert manifest["status"] == "available"
    assert manifest["count"] == 1
    assert report["report_period"] == "2026-06-30"
    assert report["announced_at"] == "2026-07-20"
    assert report["known_at"] == "2026-07-20T09:30:00+08:00"
    assert report["income"]["revenue"] == 100
    assert report["limitations"] == []


def test_interim_permission_failure_is_explicit(tmp_path):
    manifest = build_interim_reports({
        "period": "20260630", "datasets": {}, "errors": {"income": "permission denied"},
    }, tmp_path)

    assert manifest["status"] == "unavailable"
    assert manifest["source_errors"]["income"] == "permission denied"


def test_public_quarterly_reports_quarantine_future_and_dedupe(tmp_path):
    rows = [
        {
            "股票代码": "600519", "股票简称": "贵州茅台",
            "每股收益": 10.5, "净利润-净利润": 100.0,
            "最新公告日期": date(2026, 7, 24),
        },
        {
            "股票代码": "600519", "股票简称": "贵州茅台",
            "每股收益": 10.5, "净利润-净利润": 100.0,
            "最新公告日期": date(2026, 7, 24),
        },
        {
            "股票代码": "000001", "股票简称": "平安银行",
            "每股收益": 1.0, "最新公告日期": date(2026, 7, 26),
        },
        {
            "股票代码": "688001", "股票简称": "科创排除",
            "每股收益": 1.0, "最新公告日期": date(2026, 7, 24),
        },
        {
            "股票代码": "300001", "股票简称": "创业排除",
            "每股收益": 1.0, "最新公告日期": date(2026, 7, 24),
        },
    ]
    manifest = build_public_quarterly_reports(
        rows, tmp_path / "interim_reports",
        period="20260630", as_of=date(2026, 7, 25),
    )
    assert manifest["status"] == "partial"
    assert manifest["count"] == 1
    assert manifest["version_count"] == 1
    assert manifest["quarantined_future_count"] == 1
    report = json.loads((tmp_path / "interim_reports/600519.json").read_text())
    assert report["known_at"] == "2026-07-24T23:59:59+08:00"
    with gzip.open(tmp_path / manifest["history_artifact"], "rt", encoding="utf-8") as stream:
        history = json.load(stream)
    assert len(history["accepted"]) == 1
    assert history["quarantined"][0]["quarantine_reason"] == "published_after_as_of"


def test_quarter_periods_are_five_year_window_without_future_quarters():
    periods = _quarter_periods(date(2026, 7, 25))
    assert periods[0] == "20210331"
    assert periods[-1] == "20260630"
    assert "20260930" not in periods


def test_point_in_time_index_never_returns_future_record(tmp_path):
    build_public_quarterly_reports([
        {
            "股票代码": "600519", "股票简称": "贵州茅台",
            "每股收益": 1.0, "最新公告日期": date(2026, 4, 20),
        },
    ], tmp_path / "interim_reports", period="20260331", as_of=date(2026, 7, 25))
    cfg = type("Config", (), {"data_dir": tmp_path})()
    status = build_point_in_time_financial_index(cfg)
    assert status["code_count"] == 1
    assert load_financial_as_of(tmp_path, "600519", "2026-04-20T09:30:00+08:00") is None
    record = load_financial_as_of(tmp_path, "600519", "2026-04-21T09:30:00+08:00")
    assert record is not None
    assert record["report_period"] == "2026-03-31"


def test_public_refresh_failure_preserves_last_good(monkeypatch, tmp_path):
    from quant_system.tasks import interim_financial_job as job

    cfg = type("Config", (), {
        "data_dir": tmp_path,
        "tushare_enabled": False,
        "tushare_token": "",
    })()
    good = {"status": "partial", "period": "2026-06-30", "count": 44}
    job._write(tmp_path / "point_in_time_financials/status.json", good)
    monkeypatch.setattr(job, "CrawlerConfig", lambda: cfg)
    monkeypatch.setattr(job, "fetch_public_quarterly", lambda period: (_ for _ in ()).throw(ConnectionError("dns")))

    result = job.run_interim_financial_job()

    assert result["refresh_status"] == "failed_preserved_last_good"
    assert json.loads((tmp_path / "interim_reports/index.json").read_text())["count"] == 44
