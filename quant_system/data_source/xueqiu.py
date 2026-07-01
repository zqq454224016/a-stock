"""雪球舆情爬虫（Phase 2 预留）。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.models.sentiment import SentimentPost
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class XueqiuCrawler(BaseCrawler):
    source_name = "xueqiu"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)

    def fetch_spot_all(self):
        raise NotImplementedError("雪球不支持全市场行情快照")

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq"):
        raise NotImplementedError("雪球不支持日K直取，请使用 AkShareAPI")

    def fetch_posts(self, code: str, limit: int = 50) -> list[SentimentPost]:
        """Phase 2: 抓取个股帖子与评论。"""
        logger.info("[xueqiu] Phase2 未实现，code=%s", code)
        return []
