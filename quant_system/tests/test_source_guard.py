"""东财源守卫测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.utils.source_guard import disable_eastmoney, is_eastmoney_disabled, reset_eastmoney_guard


@pytest.fixture(autouse=True)
def _reset_guard():
    from quant_system.utils.source_guard import reset_all_source_guards
    reset_all_source_guards()
    yield
    reset_all_source_guards()


def test_disable_eastmoney_is_process_wide():
    disable_eastmoney("proxy fail")
    assert is_eastmoney_disabled()
    AkShareAPI()
    AkShareAPI()
    assert is_eastmoney_disabled()


def test_fetch_spot_quote_skips_bid_ask_when_disabled():
    disable_eastmoney("proxy")
    api = AkShareAPI()
    sina_df = pd.DataFrame({
        "date": ["2026-07-01", "2026-07-02"],
        "open": [10.0, 10.5],
        "high": [10.8, 11.0],
        "low": [9.8, 10.2],
        "close": [10.2, 10.8],
        "volume": [1000, 1200],
        "amount": [0, 0],
    })
    mock_ak = MagicMock()
    mock_ak.stock_bid_ask_em.side_effect = AssertionError("should not call em")
    api._ak = mock_ak
    with patch.object(api, "fetch_daily_hist", return_value=(sina_df, "sina")):
        quote = api.fetch_spot_quote("000636")
    assert quote is not None
    assert quote["close"] == 10.8
    mock_ak.stock_bid_ask_em.assert_not_called()


def test_fetch_daily_hist_skips_eastmoney_when_disabled():
    disable_eastmoney("proxy")
    api = AkShareAPI()
    sina_df = pd.DataFrame({"close": [1.0]})
    mock_ak = MagicMock()
    mock_ak.stock_zh_a_hist.side_effect = AssertionError("should not call em hist")
    mock_ak.stock_zh_a_daily.return_value = sina_df
    api._ak = mock_ak
    df, source = api.fetch_daily_hist("sz000636")
    assert source == "sina"
    mock_ak.stock_zh_a_hist.assert_not_called()


def test_note_eastmoney_failure_on_proxy_error():
    from quant_system.utils.source_guard import note_eastmoney_failure

    note_eastmoney_failure(Exception("ProxyError: Unable to connect to proxy"))
    assert is_eastmoney_disabled()
