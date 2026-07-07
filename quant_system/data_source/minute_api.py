"""分钟线数据源。"""

from __future__ import annotations

import json
import threading

import pandas as pd
import requests

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.utils.i18n_labels import humanize_fetch_error
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry
from quant_system.utils.time_utils import today_str

logger = get_logger(__name__)

_SINA_MINUTE_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
)


class MinuteAPI:
    """1/5/15 分钟 K 线采集（新浪直连，不复权）。"""

    def __init__(self, api: AkShareAPI | None = None, config: CrawlerConfig | None = None):
        self.api = api or AkShareAPI(config)
        self.config = self.api.config
        self._lock = threading.Lock()
        self._sina_disabled = False
        self._logged_disable = False

    def _disable_sina(self, err: Exception | str) -> None:
        with self._lock:
            self._sina_disabled = True
            if not self._logged_disable:
                self._logged_disable = True
                logger.warning("新浪分钟线本会话内禁用: %s", humanize_fetch_error(err))

    def _fetch_sina_minute_raw(self, symbol: str, period: str) -> pd.DataFrame:
        """直连新浪分钟线，跳过 akshare 内嵌的日 K 复权请求。"""
        params = {"symbol": symbol, "scale": period, "ma": "no", "datalen": "1970"}
        timeout = min(self.config.request_timeout, 12)
        try:
            r = requests.get(_SINA_MINUTE_URL, params=params, timeout=timeout)
            r.raise_for_status()
            data_json = json.loads(r.text.split("=(")[1].split(");")[0])
            return pd.DataFrame(data_json).iloc[:, :7]
        except Exception:
            alt_url = (
                f"https://quotes.sina.cn/cn/api/jsonp_v2.php/"
                f"var%20_{symbol}_{period}_1658852984203=/CN_MarketDataService.getKLineData"
            )
            r = requests.get(alt_url, params=params, timeout=timeout)
            r.raise_for_status()
            data_json = json.loads(r.text.split("=(")[1].split(");")[0])
            return pd.DataFrame(data_json).iloc[:, :7]

    def fetch_minute(self, symbol: str, period: str = "1", adjust: str = "") -> pd.DataFrame:
        """拉取分钟线，返回标准化 DataFrame。盘中默认不复权，避免额外日 K 请求。"""
        if self._sina_disabled:
            raise RuntimeError("sina minute disabled")

        def _do_fetch() -> pd.DataFrame:
            if adjust:
                return self.api.ak.stock_zh_a_minute(symbol=symbol, period=period, adjust=adjust)
            return self._fetch_sina_minute_raw(symbol, period)

        try:
            df = call_with_retry(
                _do_fetch,
                retries=1,
                delay=1.0,
            )
            return self._normalize(df, period)
        except Exception as e:
            self._disable_sina(e)
            raise

    @staticmethod
    def filter_latest_session(df: pd.DataFrame) -> tuple[pd.DataFrame, str, bool]:
        """
        仅保留分钟线中最近一个交易日的数据。
        返回 (df, session_date, is_today)。
        """
        if df is None or df.empty:
            return df, "", False
        work = df.copy()
        work["session_date"] = work["datetime"].dt.strftime("%Y-%m-%d")
        latest = work["session_date"].max()
        filtered = work[work["session_date"] == latest].reset_index(drop=True)
        is_today = latest == today_str()
        return filtered, latest, is_today

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
