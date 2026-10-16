"""同花顺与券商数据源注册测试。"""

from unittest.mock import MagicMock, patch

import pandas as pd

from quant_system.data_source.tonghuashun import TonghuashunCrawler


def test_ths_fetch_industries():
    ths = TonghuashunCrawler()
    df = pd.DataFrame({"板块": ["半导体", "银行"], "涨跌幅": [1.2, -0.5]})
    with patch.object(ths, "_call", return_value=df):
        rows = ths.fetch_industries()
    assert rows[0]["name"] == "半导体"
    assert rows[0]["change_pct"] == 1.2


def test_spot_fallback_includes_xueqiu_when_em_disabled():
    from quant_system.config.crawler_config import CrawlerConfig
    from quant_system.data_source.akshare_api import AkShareAPI
    from quant_system.utils.source_guard import disable_eastmoney

    disable_eastmoney("proxy")
    api = AkShareAPI(CrawlerConfig())
    order = api._spot_fallback_sources()
    assert "eastmoney" not in order
    assert "xueqiu" in order
