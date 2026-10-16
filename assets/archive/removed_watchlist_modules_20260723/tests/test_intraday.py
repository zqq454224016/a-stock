"""分钟线与盘中采集测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_system.data_source.minute_api import MinuteAPI
from quant_system.tasks.intraday_job import _fetch_minutes_safe, run_intraday_live


def _minute_df():
    return pd.DataFrame({
        "day": ["2026-07-07 09:31:00", "2026-07-07 09:32:00"],
        "open": [10.0, 10.1],
        "high": [10.2, 10.3],
        "low": [9.9, 10.0],
        "close": [10.1, 10.2],
        "volume": [100, 200],
        "amount": [1000, 2000],
    })


def test_fetch_minute_uses_direct_sina_without_akshare_daily():
    api = MagicMock()
    cfg = MagicMock()
    cfg.request_timeout = 10
    minute_api = MinuteAPI(api, cfg)
    with patch.object(minute_api, "_fetch_sina_minute_raw", return_value=_minute_df()) as mock_raw:
        df = minute_api.fetch_minute("sh600378", period="1")
    mock_raw.assert_called_once_with("sh600378", "1")
    assert len(df) == 2
    assert "datetime" in df.columns


def test_fetch_minute_disables_after_failure():
    api = MagicMock()
    cfg = MagicMock()
    cfg.request_timeout = 10
    minute_api = MinuteAPI(api, cfg)
    with patch.object(minute_api, "_fetch_sina_minute_raw", side_effect=RuntimeError("proxy")):
        with pytest.raises(RuntimeError):
            minute_api.fetch_minute("sh600378", period="1")
        with pytest.raises(RuntimeError, match="disabled"):
            minute_api.fetch_minute("sh600378", period="1")


def test_fetch_minutes_safe_skips_5m_when_disabled():
    api = MagicMock()
    cfg = MagicMock()
    cfg.request_timeout = 10
    minute_api = MinuteAPI(api, cfg)
    minute_api._sina_disabled = True
    m1, date, is_today, m5 = _fetch_minutes_safe(minute_api, "sh603629", "603629")
    assert m1.empty
    assert m5 is None


def test_run_intraday_live_spot_only_when_minute_fails():
    from quant_system.config.crawler_config import CrawlerConfig

    cfg = CrawlerConfig()
    with patch("quant_system.tasks.intraday_job.AkShareAPI") as MockApi:
        with patch("quant_system.tasks.intraday_job.MinuteAPI") as MockMinute:
            with patch("quant_system.tasks.intraday_job.JsonStore") as MockStore:
                with patch("quant_system.tasks.intraday_job.RedisClient") as MockRedis:
                    api = MockApi.return_value
                    api.fetch_spot_map.return_value = {
                        "603629": {
                            "close": 173.0, "change_pct": 3.0, "name": "利通电子",
                            "open": 170, "high": 175, "low": 168, "volume": 1, "amount_yi": 1,
                        },
                    }
                    minute_api = MockMinute.return_value
                    minute_api._sina_disabled = False
                    minute_api.fetch_minute.side_effect = RuntimeError("network")
                    store = MockStore.return_value
                    store.read.return_value = {}
                    redis = MockRedis.return_value

                    out = run_intraday_live(codes=["603629"])

    assert len(out) == 1
    assert out[0]["code"] == "603629"
    store.save_live_stock.assert_called_once()
    redis.set_json.assert_called_once()
