"""P1-3 数据增强采集门面（估值/公司行为/资金/指数）。"""

from __future__ import annotations

import threading

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.data_source.enhance.bundle import BundleProviderMixin
from quant_system.data_source.enhance.corporate import CorporateProviderMixin
from quant_system.data_source.enhance.fund_flow import FundFlowProviderMixin
from quant_system.data_source.enhance.runtime import EnhanceRuntimeMixin
from quant_system.data_source.enhance.valuation import ValuationProviderMixin
from quant_system.data_source.tonghuashun import TonghuashunCrawler


class EnhanceAPI(
    EnhanceRuntimeMixin,
    ValuationProviderMixin,
    CorporateProviderMixin,
    FundFlowProviderMixin,
    BundleProviderMixin,
    BaseCrawler,
):
    """个股增强数据：估值、公司行为、北向/两融、指数对照。"""

    source_name = "数据增强"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None
        self._ths = TonghuashunCrawler(config)
        self._lock = threading.Lock()
        self._disabled: set[str] = set()
        self._disabled_prefixes: set[str] = set()
        self._logged_failures: set[str] = set()

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_spot_all(self) -> pd.DataFrame:
        raise NotImplementedError

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        raise NotImplementedError
