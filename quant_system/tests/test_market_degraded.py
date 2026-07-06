"""大盘快照降级单元测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.validator import ValidationError, validate_market_snapshot


def test_fetch_market_snapshot_bulk_fail_watchlist_fallback():
    api = AkShareAPI(CrawlerConfig())
    store = MagicMock()
    store.config.json_data_dir = MagicMock()
    store.read.return_value = {"indices": [], "top_gainers": []}

    with patch.object(api, "_fetch_spot_map_per_code", return_value={
        "600378": {"close": 70.0, "change_pct": 1.2, "name": "昊华科技", "amount_yi": 1.0},
    }):
        with patch.object(api, "fetch_fund_flow", return_value=({"north_net": 0.0, "main_net": 0.0, "retail_net": 0.0}, "2026-07-06")):
            with patch.object(api, "fetch_indices", return_value=[{"name": "上证指数", "code": "000001", "close": 4000, "change_pct": -1.0}]):
                with patch.object(api, "fetch_industries", return_value=[]):
                    data = api.fetch_market_snapshot(store=store)

    assert data["degraded"] is True
    assert "bulk_spot_skipped" in data["limitations"]
    assert data["spot_scope"] == "watchlist"
    assert len(data["top_gainers"]) == 1
    validate_market_snapshot(data)


def test_validate_market_degraded_needs_indices_or_gainers():
    with pytest.raises(ValidationError):
        validate_market_snapshot({"trade_date": "2026-07-06", "degraded": True})
