"""雪球舆情与行情爬虫。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.models.sentiment import SentimentPost
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)


def _xq_symbol(code: str) -> str:
    code = normalize_code(code)
    if code.startswith(("8", "4", "9")):
        return f"BJ{code}"
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


class XueqiuCrawler(BaseCrawler):
    source_name = "雪球"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_spot_all(self):
        raise NotImplementedError("雪球不支持全市场行情快照")

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq"):
        raise NotImplementedError("雪球不支持日K直取，请使用 AkShareAPI")

    def fetch_spot_quote(self, code: str) -> dict[str, Any] | None:
        code = normalize_code(code)
        symbol = _xq_symbol(code)
        df = call_with_retry(
            lambda: self.ak.stock_individual_spot_xq(symbol=symbol, timeout=12),
            retries=1,
            delay=1.0,
        )
        if df is None or df.empty:
            return None
        mapping = dict(zip(df["item"].astype(str), df["value"]))
        close = float(mapping.get("现价", 0) or 0)
        if close <= 0:
            return None
        amount = float(mapping.get("成交额", 0) or 0)
        return {
            "close": close,
            "change": float(mapping.get("涨跌", 0) or 0),
            "change_pct": float(mapping.get("涨幅", 0) or 0),
            "open": float(mapping.get("今开", 0) or 0),
            "high": float(mapping.get("最高", 0) or 0),
            "low": float(mapping.get("最低", 0) or 0),
            "volume": float(mapping.get("成交量", 0) or 0),
            "amount_yi": round(amount / 1e8, 2),
            "name": str(mapping.get("名称", "") or ""),
            "quote_source": "xueqiu",
        }

    def fetch_posts(self, code: str, limit: int = 50) -> list[SentimentPost]:
        """Phase 2: 抓取个股帖子与评论。"""
        logger.info("[雪球] Phase2 未实现，code=%s", code)
        return []
