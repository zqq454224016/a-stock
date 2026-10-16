from quant_system.analysis.today_change import analyze_stock_change, change_bucket, summarize_today
from quant_system.tasks import today_change_job


def _stock(change_pct: float = 5.0):
    return {
        "code": "600001",
        "name": "测试股份",
        "trade_date": "2026-07-23",
        "quote": {
            "close": 10.5,
            "open": 10.1,
            "high": 10.8,
            "low": 10.0,
            "volume": 2000,
            "change_pct": change_pct,
        },
        "kline": [
            {"close": 9.8, "volume": 900},
            {"close": 9.9, "volume": 1000},
            {"close": 10.0, "volume": 1100},
            {"close": 10.5, "volume": 2000},
        ],
    }


def test_stock_change_separates_gap_intraday_volume_and_relative_strength():
    payload = analyze_stock_change(_stock(), benchmark_change_pct=1.0)

    assert payload["bucket"] == "strong_up"
    assert payload["gap_pct"] == 1.0
    assert payload["intraday_pct"] == 3.96
    assert payload["relative_strength_pct"] == 4.0
    assert payload["volume_ratio_5d"] == 2.0
    assert "明显跑赢市场" in payload["drivers"]


def test_today_summary_reports_breadth_and_median():
    rows = [
        {"code": "1", "change_pct": 2, "bucket": change_bucket(2)},
        {"code": "2", "change_pct": 1, "bucket": change_bucket(1)},
        {"code": "3", "change_pct": -1, "bucket": change_bucket(-1)},
    ]
    payload = summarize_today(
        rows,
        trade_date="2026-07-23",
        industries=[{"name": "银行", "change_pct": 1.5}, {"name": "游戏", "change_pct": -2}],
    )

    assert payload["breadth"]["advances"] == 2
    assert payload["breadth"]["declines"] == 1
    assert payload["median_change_pct"] == 1
    assert payload["market_state"] == "普涨"
    assert payload["leading_industries"][0]["name"] == "银行"


def test_job_uses_most_covered_date_instead_of_small_manual_refresh(monkeypatch, tmp_path):
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    for code, date in (("600001", "2026-07-22"), ("600002", "2026-07-22"), ("600003", "2026-07-23")):
        payload = _stock(1)
        payload.update(code=code, trade_date=date)
        (stocks / f"{code}.json").write_text(__import__("json").dumps(payload), encoding="utf-8")
    (tmp_path / "latest.json").write_text('{"indices":[],"industries":[]}', encoding="utf-8")
    monkeypatch.setattr(today_change_job, "CrawlerConfig", lambda: type("Config", (), {"data_dir": tmp_path})())

    payload = today_change_job.run_today_change_job()

    assert payload["trade_date"] == "2026-07-22"
    assert payload["latest_observed_trade_date"] == "2026-07-23"
    assert payload["sample_count"] == 2
