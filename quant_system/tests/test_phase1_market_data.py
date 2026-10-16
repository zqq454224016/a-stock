from pathlib import Path
from types import SimpleNamespace

from quant_system.tasks import phase1_market_data_job as job


def test_trading_status_snapshot_marks_unknown_suspension(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    path = job._trading_status_snapshot([{
        "symbol": "600000.SH", "code": "600000", "name": "浦发银行", "exchange": "SH",
        "is_st": False, "limit_up": 10.5, "limit_down": 8.5, "listing_date": "1999-11-10",
    }], cfg)
    payload = __import__("json").loads(path.read_text())
    assert payload["quality"]["status"] == "partial"
    assert payload["items"][0]["is_suspended"] is None


def test_trading_status_merges_tushare_facts(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    supplement = {
        "suspended": [{"ts_code": "600000.SH"}],
        "st": [{"ts_code": "600000.SH"}],
        "securities": [{"ts_code": "600000.SH", "list_status": "P", "list_date": "19991110"}],
        "errors": {},
    }
    path = job._trading_status_snapshot([{
        "symbol": "600000.SH", "code": "600000", "name": "浦发银行", "exchange": "SH",
        "is_st": False, "limit_up": 10.5, "limit_down": 8.5, "listing_date": "",
    }], cfg, supplement)
    item = __import__("json").loads(path.read_text())["items"][0]
    assert item["is_suspended"] is True
    assert item["is_st"] is True
    assert item["list_status"] == "P"
    assert item["source"] == "tickflow+tushare"


def test_ex_factor_permission_failure_is_visible(tmp_path):
    class API:
        def fetch_ex_factors(self, symbols):
            raise PermissionError("无除权因子权限")

    cfg = SimpleNamespace(data_dir=tmp_path)
    payload = job._sync_ex_factors(API(), ["600000"], cfg)
    assert payload["status"] == "unavailable"
    assert "权限" in payload["error"]
    assert (tmp_path / "normalized" / "market.corporate_actions" / "ex_factors.json").exists()


def test_universe_quality_gate_requires_three_exchanges():
    rows = [
        {"code": "600000", "exchange": "SH"},
        {"code": "000001", "exchange": "SZ"},
        {"code": "920001", "exchange": "BJ"},
    ]
    assert job._validate_universe(rows)["status"] == "valid"
    assert job._validate_universe(rows + [rows[0]])["status"] == "invalid"


def test_security_master_keeps_delisted_securities(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    universe = [{
        "symbol": "600000.SH", "code": "600000", "name": "浦发银行",
        "exchange": "SH", "listing_date": "1999-11-10",
    }]
    supplement = {"securities": [
        {"ts_code": "600000.SH", "symbol": "600000", "name": "浦发银行", "exchange": "SSE", "list_status": "L", "list_date": "19991110"},
        {"ts_code": "600001.SH", "symbol": "600001", "name": "退市样本", "exchange": "SSE", "list_status": "D", "list_date": "19901219", "delist_date": "20010806"},
    ]}

    payload = job._security_master(universe, supplement, cfg)

    assert payload["count"] == 2
    assert payload["list_status_counts"] == {"L": 1, "D": 1}
    delisted = next(item for item in payload["items"] if item["symbol"] == "600001.SH")
    assert delisted["effective_to"] == "2001-08-06"
    assert delisted["sources"] == ["tushare"]
    assert (tmp_path / "normalized" / "market.instruments" / "security_master.json").exists()


def test_status_history_extends_unchanged_observation(tmp_path, monkeypatch):
    cfg = SimpleNamespace(data_dir=tmp_path)
    item = {"symbol": "600000.SH", "name": "浦发银行", "is_st": False, "limit_up": 10.5, "limit_down": 8.5}
    path = job._update_status_history([item], cfg)
    first = __import__("json").loads(path.read_text())
    path = job._update_status_history([item], cfg)
    second = __import__("json").loads(path.read_text())
    assert len(first["items"]) == len(second["items"]) == 1
    assert second["items"][0]["history_semantics"] == "observed_by_this_system_not_backfilled"


def test_status_events_are_merged_without_duplicates(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path)
    incoming = {
        "errors": {},
        "suspension_events": [{"ts_code": "600000.SH", "trade_date": "20260721", "suspend_type": "S"}],
        "st_daily": [{"ts_code": "000001.SZ", "trade_date": "20260721", "type": "S", "type_name": "ST"}],
    }
    first = job._merge_status_events(incoming, cfg)
    second = job._merge_status_events(incoming, cfg)

    assert first["count"] == second["count"] == 2
    assert second["coverage_start"] == "2026-07-21"
    assert all(item["known_at"].endswith("15:00:00+08:00") for item in second["items"])
