from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from quant_system.analysis.sector_rotation import build_sector_rotation
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks import sector_data_job
from quant_system.tasks.sector_data_job import run_sector_data_job


def _kline_rows(end: str, count: int = 25, start_close: float = 100.0) -> list[dict]:
    last = date.fromisoformat(end)
    rows = []
    for index in range(count):
        day = last - timedelta(days=count - 1 - index)
        close = start_close + index
        rows.append({
            "日期": day.isoformat(),
            "开盘": close - 1,
            "最高": close + 1,
            "最低": close - 2,
            "收盘": close,
            "涨跌幅": 1.0,
            "成交量": 1000,
            "成交额": 1_000_000 + index,
        })
    return rows


def _write_history(root, industry: str, end: str, start_close: float = 100.0, start: str | None = None) -> None:
    rows = [
        {
            "date": row["日期"],
            "open": row["开盘"],
            "high": row["最高"],
            "low": row["最低"],
            "close": row["收盘"],
            "change_pct": row["涨跌幅"],
            "volume": row["成交量"],
            "amount": row["成交额"],
        }
        for row in _kline_rows(end, start_close=start_close)
    ]
    if start:
        rows[0]["date"] = start
    path = root / "sector_data" / "history" / f"{industry}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "industry": industry,
        "start_date": rows[0]["date"],
        "end_date": rows[-1]["date"],
        "rows": rows,
    }), encoding="utf-8")


class FakeAk:
    hist_calls = 0

    @staticmethod
    def stock_board_industry_name_em():
        return pd.DataFrame([{"板块名称": "测试行业", "板块代码": "BK0001", "涨跌幅": 2.1}])

    @staticmethod
    def stock_board_industry_cons_em(symbol):
        return pd.DataFrame([
            {"代码": "600001", "名称": "测试股份"},
            {"代码": "300001", "名称": "权限板块"},
        ])

    @staticmethod
    def stock_board_industry_hist_em(**kwargs):
        FakeAk.hist_calls += 1
        return pd.DataFrame(_kline_rows("2026-07-29"))


def test_sector_data_builds_mapping_and_history(monkeypatch, tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    FakeAk.hist_calls = 0
    monkeypatch.setattr(sector_data_job, "_public_industry_mapping", lambda: [])
    monkeypatch.setattr(sector_data_job, "_target_history_end", lambda: "2026-07-29")

    status = run_sector_data_job(cfg, ak_module=FakeAk(), years=5)

    assert status["status"] == "complete"
    assert status["stock_mapping_count"] == 1
    assert status["latest_trade_date"] == "2026-07-29"
    assert status["attempted_trade_date"] == "2026-07-29"
    mapping = (tmp_path / "sector_data/stock_industry_map.json").read_text(encoding="utf-8")
    assert "600001" in mapping
    assert "300001" not in mapping
    assert (tmp_path / "sector_data/history/测试行业.json").exists()
    rotation = json.loads((tmp_path / "sector_data/rotation.json").read_text(encoding="utf-8"))
    assert rotation["trade_date"] == "2026-07-29"
    assert rotation["count"] == 1


def test_sector_history_skips_when_covering_latest_session(monkeypatch, tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    FakeAk.hist_calls = 0
    _write_history(tmp_path, "测试行业", "2026-09-11", start="2020-01-02")
    monkeypatch.setattr(sector_data_job, "_public_industry_mapping", lambda: [])
    monkeypatch.setattr(sector_data_job, "_target_history_end", lambda: "2026-09-11")

    status = run_sector_data_job(cfg, ak_module=FakeAk(), years=5)

    assert status["history_completed"] == 1
    assert FakeAk.hist_calls == 0
    assert status["latest_trade_date"] == "2026-09-11"
    assert status["attempted_trade_date"] == "2026-09-11"


def test_sector_history_refreshes_when_behind_latest_session(monkeypatch, tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    FakeAk.hist_calls = 0
    _write_history(tmp_path, "测试行业", "2026-09-10", start="2020-01-02")
    monkeypatch.setattr(sector_data_job, "_public_industry_mapping", lambda: [])
    monkeypatch.setattr(sector_data_job, "_target_history_end", lambda: "2026-09-11")

    class RefreshAk(FakeAk):
        @staticmethod
        def stock_board_industry_hist_em(**kwargs):
            FakeAk.hist_calls += 1
            return pd.DataFrame(_kline_rows("2026-09-11"))

    status = run_sector_data_job(cfg, ak_module=RefreshAk(), years=5)

    assert FakeAk.hist_calls == 1
    assert status["latest_trade_date"] == "2026-09-11"
    history = json.loads((tmp_path / "sector_data/history/测试行业.json").read_text(encoding="utf-8"))
    assert history["end_date"] == "2026-09-11"


def test_sector_rotation_ignores_stale_history_files(tmp_path):
    _write_history(tmp_path, "旧板块", "2026-08-20", start_close=80)
    _write_history(tmp_path, "新板块", "2026-09-10", start_close=120)

    payload = build_sector_rotation(tmp_path)

    assert payload["trade_date"] == "2026-09-10"
    assert payload["count"] == 1
    assert payload["items"][0]["industry"] == "新板块"
