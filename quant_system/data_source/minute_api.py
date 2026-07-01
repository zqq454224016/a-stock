"""分钟线数据源。"""

from __future__ import annotations

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)


class MinuteAPI:
    """1/5/15 分钟 K 线采集（新浪）。"""

    def __init__(self, api: AkShareAPI | None = None, config: CrawlerConfig | None = None):
        self.api = api or AkShareAPI(config)
        self.config = self.api.config

    def fetch_minute(self, symbol: str, period: str = "1", adjust: str = "qfq") -> pd.DataFrame:
        """拉取分钟线，返回标准化 DataFrame。"""
        df = call_with_retry(
            lambda: self.api.ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust),
            retries=self.config.retry_times,
            delay=self.config.retry_delay,
        )
        return self._normalize(df, period)

    def _normalize(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        col_map = {"day": "datetime", "date": "datetime"}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if "datetime" not in df.columns:
            raise ValueError("分钟线缺少时间列")

        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["period"] = period
        return df.dropna(subset=["close"])
