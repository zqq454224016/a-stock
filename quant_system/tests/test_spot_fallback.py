"""实时行情降级单元测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.akshare_api import AkShareAPI


def _bulk_df():
    return pd.DataFrame([{
        "代码": "600378", "名称": "昊华科技", "最新价": 70.0, "涨跌额": -1.0,
        "涨跌幅": -1.4, "今开": 71.0, "最高": 72.0, "最低": 69.0,
        "成交量": 1000.0, "成交额": 7e8,
    }])


def _bid_ask_df():
    return pd.DataFrame([
        {"item": "最新", "value": 69.91},
        {"item": "涨跌", "value": -6.1},
        {"item": "涨幅", "value": -8.03},
        {"item": "今开", "value": 76.88},
        {"item": "最高", "value": 79.8},
        {"item": "最低", "value": 69.3},
        {"item": "总手", "value": 740042},
        {"item": "金额", "value": 5.49e9},
    ])


def test_fetch_spot_map_skips_bulk_for_small_watchlist():
    api = AkShareAPI(CrawlerConfig())
    with patch.object(api, "fetch_spot_all", side_effect=AssertionError("should not call bulk")):
        with patch.object(api, "fetch_spot_quote", return_value={"close": 69.91, "change_pct": -8.0, "name": ""}):
            spot = api.fetch_spot_map(codes=["600378"])
    assert spot["600378"]["close"] == 69.91


def test_fetch_spot_map_bulk_fail_watchlist_fallback():
    cfg = CrawlerConfig()
    cfg.watchlist_spot_threshold = 0  # 强制走全市场路径
    api = AkShareAPI(cfg)
    with patch.object(api, "fetch_spot_all", side_effect=RuntimeError("sina html")):
        with patch.object(api, "fetch_spot_quote", return_value={"close": 69.91, "change_pct": -8.0, "name": ""}):
            spot = api.fetch_spot_map(codes=["600378"])
    assert spot["600378"]["close"] == 69.91


def test_fetch_spot_all_source_order_sina_first():
    cfg = CrawlerConfig()
    cfg.prefer_source = "sina"
    api = AkShareAPI(cfg)
    assert api._spot_source_order()[0] == "sina"


def test_parse_bid_ask():
    api = AkShareAPI()
    quote = api._parse_bid_ask("600378", _bid_ask_df())
    assert quote["close"] == 69.91
    assert quote["quote_source"] == "bid_ask"
