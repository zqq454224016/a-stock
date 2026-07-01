"""爬虫基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)


class BaseCrawler(ABC):
    source_name: str = "base"

    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()

    def _retry(self, fn, *args, **kwargs):
        return call_with_retry(
            fn,
            retries=self.config.retry_times,
            delay=self.config.retry_delay,
            *args,
            **kwargs,
        )

    @abstractmethod
    def fetch_spot_all(self) -> pd.DataFrame:
        ...

    @abstractmethod
    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        ...

    def log_ok(self, msg: str) -> None:
        logger.info("[%s] %s", self.source_name, msg)

    def log_fail(self, msg: str) -> None:
        logger.warning("[%s] %s", self.source_name, msg)
