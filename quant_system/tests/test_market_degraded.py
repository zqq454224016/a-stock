"""大盘快照降级单元测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.validator import ValidationError, validate_market_snapshot
from quant_system.storage.json_store import JsonStore
from quant_system.config.db_config import DBConfig


def test_fetch_market_snapshot_bulk_fail_does_not_fetch_individual_codes():
    api = AkShareAPI(CrawlerConfig())
    store = MagicMock()
    store.config.json_data_dir = MagicMock()
    store.read.return_value = {"indices": [], "top_gainers": []}

    with patch.object(api, "fetch_spot_all", side_effect=RuntimeError("bulk unavailable")):
        with patch.object(api, "_fetch_spot_map_per_code", return_value={
        "600378": {"close": 70.0, "change_pct": 1.2, "name": "昊华科技", "amount_yi": 1.0},
        }):
            with patch.object(api, "fetch_fund_flow", return_value=({"north_net": 0.0, "main_net": 0.0, "retail_net": 0.0}, "2026-07-06")):
                with patch.object(api, "fetch_indices", return_value=[{"name": "上证指数", "code": "000001", "close": 4000, "change_pct": -1.0}]):
                    with patch.object(api, "fetch_industries", return_value=[]):
                        data = api.fetch_market_snapshot(store=store)

    assert data["degraded"] is True
    assert "bulk_spot_failed" in data["limitations"]
    assert data["spot_scope"] == "none"
    assert data["top_gainers"] == []
    validate_market_snapshot(data)


def test_validate_market_degraded_needs_indices_or_gainers():
    with pytest.raises(ValidationError):
        validate_market_snapshot({"trade_date": "2026-07-06", "degraded": True})


def test_stock_cache_uses_majority_session_and_never_invents_today(tmp_path):
    config = DBConfig()
    config.json_data_dir = tmp_path
    store = JsonStore(config)
    stocks = tmp_path / "stocks"
    store.write(stocks / "600001.json", {
        "trade_date": "2026-08-05", "name": "旧一",
        "quote": {"close": 10, "change_pct": 1, "amount_yi": 1},
    })
    store.write(stocks / "600002.json", {
        "trade_date": "2026-08-05", "name": "旧二",
        "quote": {"close": 11, "change_pct": 2, "amount_yi": 1},
    })
    store.write(stocks / "600003.json", {
        "trade_date": "2026-08-25", "name": "新少数",
        "quote": {"close": 12, "change_pct": 9, "amount_yi": 1},
    })
    # This contaminated summary must not redefine the cache session.
    store.write(tmp_path / "today_change/summary.json", {"trade_date": "2026-08-25"})

    api = AkShareAPI(CrawlerConfig())
    with patch.object(api, "fetch_spot_all", side_effect=RuntimeError("bulk unavailable")), \
         patch.object(api, "fetch_fund_flow", return_value=({}, "")), \
         patch.object(api, "fetch_indices", return_value=[
             {"name": "上证指数", "code": "000001", "close": 4000, "change_pct": 0},
             {"name": "深证成指", "code": "399001", "close": 13000, "change_pct": 0},
         ]), \
         patch.object(api, "fetch_industries", return_value=[]):
        data = api.fetch_market_snapshot(store=store)

    assert data["trade_date"] == "2026-08-05"
    assert data["component_trade_dates"]["stock_rankings"] == "2026-08-05"
    assert "spot_stock_cache_stale" in data["limitations"]
    assert {row["code"] for row in data["top_gainers"]} == {"600001", "600002"}
