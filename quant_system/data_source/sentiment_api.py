"""舆情数据采集（东财评论 + 雪球热榜）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.data_source.xueqiu import XueqiuCrawler
from quant_system.models.sentiment import SentimentPost
from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str, today_str

logger = get_logger(__name__)


def _norm_xq_code(code: str) -> str:
    c = normalize_code(code)
    prefix = "SH" if c.startswith("6") else "SZ"
    if c.startswith(("8", "4", "9")):
        prefix = "BJ"
    return f"{prefix}{c}"


class SentimentAPI(BaseCrawler):
    """个股舆情：东财评论指标为主，雪球热榜热度为辅。"""

    source_name = "sentiment"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None
        self._xq = XueqiuCrawler(config)
        self._comment_cache: pd.DataFrame | None = None

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_spot_all(self) -> pd.DataFrame:
        raise NotImplementedError("舆情 API 不提供全市场行情")

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        raise NotImplementedError("舆情 API 不提供日 K")

    def _load_comment_table(self) -> pd.DataFrame:
        if self._comment_cache is not None:
            return self._comment_cache
        df = self._retry(self.ak.stock_comment_em)
        df = df.copy()
        df["代码"] = df["代码"].astype(str).map(normalize_code)
        self._comment_cache = df
        self.log_ok(f"东财评论快照 {len(df)} 只")
        return df

    def fetch_em_snapshot(self, code: str) -> dict[str, Any] | None:
        code = normalize_code(code)
        df = self._load_comment_table()
        row = df[df["代码"] == code]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "composite_score": float(r.get("综合得分", 0) or 0),
            "focus_index": float(r.get("关注指数", 0) or 0),
            "rank": int(r.get("目前排名", 0) or 0),
            "rank_change": float(r.get("上升", 0) or 0),
            "trade_date": str(r.get("交易日", today_str()))[:10],
        }

    def fetch_em_series(self, code: str) -> dict[str, list[dict]]:
        code = normalize_code(code)
        out: dict[str, list[dict]] = {}
        fetchers = {
            "desire": lambda: self.ak.stock_comment_detail_scrd_desire_em(symbol=code),
            "focus": lambda: self.ak.stock_comment_detail_scrd_focus_em(symbol=code),
            "institution": lambda: self.ak.stock_comment_detail_zlkp_jgcyd_em(symbol=code),
        }
        for key, fn in fetchers.items():
            try:
                df = self._retry(fn)
                rows = []
                for _, r in df.iterrows():
                    date_col = "交易日期" if "交易日期" in df.columns else "交易日"
                    rows.append({
                        "date": str(r[date_col])[:10],
                        **{k: float(v) if isinstance(v, (int, float)) else v
                           for k, v in r.items() if k != date_col},
                    })
                out[key] = rows
            except Exception as e:
                logger.warning("东财评论序列 %s %s: %s", code, key, e)
                out[key] = []
        return out

    def fetch_xueqiu_hot(self, code: str) -> dict[str, Any]:
        xq_code = _norm_xq_code(code)
        hot: dict[str, Any] = {
            "in_hot_tweet": False,
            "in_hot_follow": False,
            "in_hot_deal": False,
            "tweet_rank": None,
            "follow_rank": None,
            "deal_rank": None,
            "tweet_heat": 0,
            "follow_heat": 0,
            "deal_heat": 0,
        }
        for list_name, fn_name in (
            ("tweet", "stock_hot_tweet_xq"),
            ("follow", "stock_hot_follow_xq"),
            ("deal", "stock_hot_deal_xq"),
        ):
            try:
                df = self._retry(getattr(self.ak, fn_name))
                df = df.copy()
                df["norm"] = df["股票代码"].astype(str).str.upper()
                hit = df[df["norm"] == xq_code]
                if hit.empty:
                    continue
                idx = int(hit.index[0]) + 1
                heat = int(float(hit.iloc[0].get("关注", 0) or 0))
                hot[f"in_hot_{list_name}"] = True
                hot[f"{list_name}_rank"] = idx
                hot[f"{list_name}_heat"] = heat
            except Exception as e:
                logger.warning("雪球热榜 %s 不可用: %s", list_name, e)
        return hot

    def fetch_stock_sentiment(self, code: str) -> dict[str, Any]:
        code = normalize_code(code)
        em = self.fetch_em_snapshot(code)
        series = self.fetch_em_series(code)
        xq = self.fetch_xueqiu_hot(code)

        posts: list[SentimentPost] = []
        if xq.get("in_hot_tweet"):
            posts.append(SentimentPost(
                code=code,
                platform="xueqiu",
                title=f"雪球热议榜 #{xq['tweet_rank']}",
                content=f"关注热度 {xq['tweet_heat']}",
                author="xueqiu_hot",
                publish_time=now_str(),
                likes=xq["tweet_heat"],
                heat=float(xq["tweet_heat"]),
                label="中性",
            ))

        return {
            "code": code,
            "symbol": to_symbol(code),
            "trade_date": (em or {}).get("trade_date") or today_str(),
            "fetched_at": now_str(),
            "em_snapshot": em,
            "em_series": series,
            "xueqiu_hot": xq,
            "posts": [p.to_dict() for p in posts],
            "sources": ["eastmoney", "xueqiu"],
        }
