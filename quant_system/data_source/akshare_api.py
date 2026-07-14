"""AkShare 数据源门面（多 Provider 组合 + 自动降级）。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.data_source.eastmoney import EastMoneyCrawler
from quant_system.data_source.providers.daily import DailyProviderMixin
from quant_system.data_source.providers.market_meta import MarketMetaProviderMixin
from quant_system.data_source.providers.snapshot import SnapshotProviderMixin
from quant_system.data_source.providers.spot import SpotProviderMixin
from quant_system.data_source.providers.spot_quote import SpotQuoteProviderMixin
from quant_system.data_source.tonghuashun import TonghuashunCrawler
from quant_system.data_source.xueqiu import XueqiuCrawler
from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import (
    disable_eastmoney,
    ensure_eastmoney_policy,
    is_eastmoney_disabled,
    note_eastmoney_failure,
)


class AkShareAPI(
    SpotProviderMixin,
    SpotQuoteProviderMixin,
    DailyProviderMixin,
    MarketMetaProviderMixin,
    SnapshotProviderMixin,
    BaseCrawler,
):
    source_name = "akshare"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None
        self._em = EastMoneyCrawler(config)
        self._ths = TonghuashunCrawler(config)
        self._xq = XueqiuCrawler(config)
        ensure_eastmoney_policy(self.config.disable_eastmoney)
        if self.config.disable_ths:
            from quant_system.utils.source_guard import disable_ths
            disable_ths(reason="已配置跳过同花顺")

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def _try_eastmoney(self, fn, label: str):
        """尝试东财接口；失败一次后本会话内不再重试东财（仅用于非行情类探测）。"""
        if is_eastmoney_disabled():
            return None
        try:
            return call_with_retry(
                fn,
                retries=self.config.eastmoney_probe_retries,
                delay=self.config.retry_delay,
            )
        except Exception as e:
            note_eastmoney_failure(e)
            self.log_fail(f"东财{label}不可用，已切换备用源: {e}")
            return None

    def _disable_eastmoney(self, err: Exception | None = None) -> None:
        disable_eastmoney(err)
