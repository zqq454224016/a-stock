"""AkShare 数据源（多接口封装 + 自动降级）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.data_source.eastmoney import EastMoneyCrawler
from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)


class AkShareAPI(BaseCrawler):
    source_name = "akshare"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None
        self._em = EastMoneyCrawler(config)
        self._eastmoney_disabled = self.config.prefer_source == "sina"

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def _try_eastmoney(self, fn, label: str):
        """尝试东财接口；失败一次后本会话内不再重试东财。"""
        if self._eastmoney_disabled or self.config.prefer_source == "sina":
            return None
        try:
            return call_with_retry(
                fn,
                retries=self.config.eastmoney_probe_retries,
                delay=self.config.retry_delay,
            )
        except Exception as e:
            self._eastmoney_disabled = True
            self.log_fail(f"东财{label}不可用，已切换备用源: {e}")
            return None

    def fetch_spot_all(self) -> pd.DataFrame:
        if self.config.prefer_source != "sina":
            df = self._try_eastmoney(self._em.fetch_spot_all, "个股")
            if df is not None:
                self.log_ok(f"个股快照：东财 {len(df)} 只")
                return df

        df = self._retry(self.ak.stock_zh_a_spot)
        self.log_ok(f"个股快照：新浪 {len(df)} 只")
        return df

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> tuple[pd.DataFrame, str]:
        """拉取日 K，返回 (DataFrame, source)。日 K 优先东财（通常含当日）。"""
        code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        try:
            df = call_with_retry(
                lambda: self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust),
                retries=self.config.eastmoney_probe_retries,
                delay=self.config.retry_delay,
            )
            if df is not None and not df.empty:
                self.log_ok(f"日K {symbol}：东财 {len(df)} 条")
                return df, "eastmoney"
        except Exception as e:
            self.log_fail(f"东财日K不可用: {e}")

        try:
            df = self._retry(lambda: self.ak.stock_zh_a_daily(symbol=symbol, adjust=adjust))
            self.log_ok(f"日K {symbol}：新浪 {len(df)} 条")
            return df, "sina"
        except Exception as e:
            self.log_fail(f"新浪日K不可用: {e}")

        df = self._retry(lambda: self.ak.stock_zh_a_hist_tx(symbol=symbol, adjust=adjust))
        self.log_ok(f"日K {symbol}：腾讯 {len(df)} 条")
        return df, "tencent"

    def fetch_daily_hist_source(self, symbol: str, source: str, adjust: str = "qfq") -> pd.DataFrame:
        """按指定来源拉取日 K（用于跨源校验）。"""
        code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        if source == "eastmoney":
            return self._retry(
                lambda: self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust)
            )
        if source == "sina":
            return self._retry(lambda: self.ak.stock_zh_a_daily(symbol=symbol, adjust=adjust))
        if source == "tencent":
            return self._retry(lambda: self.ak.stock_zh_a_hist_tx(symbol=symbol, adjust=adjust))
        raise ValueError(f"未知日K来源: {source}")

    def fetch_indices(self) -> list[dict[str, Any]]:
        if self.config.prefer_source != "sina":
            try:
                indices = self._em.fetch_indices()
                if indices:
                    return indices
            except Exception as e:
                self.log_fail(f"东财指数不可用: {e}")

        index_df = self._retry(self.ak.stock_zh_index_spot_sina)
        indices = []
        for sina_code, (code, name) in self.config.index_map_sina.items():
            row = index_df[index_df["代码"] == sina_code]
            if row.empty:
                continue
            r = row.iloc[0]
            indices.append({
                "name": name, "code": code,
                "close": float(r["最新价"]),
                "change": float(r["涨跌额"]),
                "change_pct": float(r["涨跌幅"]),
            })
        self.log_ok(f"指数：新浪 {len(indices)} 个")
        return indices

    def fetch_industries(self) -> list[dict[str, Any]]:
        if self.config.prefer_source != "sina":
            try:
                return self._em.fetch_industries()
            except Exception as e:
                self.log_fail(f"东财行业不可用: {e}")

        industry_df = self._retry(lambda: self.ak.stock_fund_flow_industry(symbol="即时"))
        industries = [
            {"name": str(r["行业"]), "change_pct": float(r["行业-涨跌幅"])}
            for _, r in industry_df.head(self.config.industry_top_n).iterrows()
        ]
        self.log_ok(f"行业：同花顺 {len(industries)} 个")
        return industries

    def fetch_fund_flow(self) -> tuple[dict[str, float], str | None]:
        return self._em.fetch_fund_flow()

    def fetch_spot_map(self, codes: list[str] | None = None) -> dict[str, dict]:
        """全市场或指定代码的实时快照。自选股也会拉实时价（新浪需全市场接口后过滤）。"""
        codes_set = {normalize_code(c) for c in codes} if codes else None

        if codes_set and len(codes_set) <= 10:
            logger.info("自选股 %s 只，拉取实时行情…", len(codes_set))
        else:
            logger.info("拉取全市场实时行情…")

        df = self.fetch_spot_all()
        spot_map = {}
        for _, r in df.iterrows():
            code = normalize_code(str(r["代码"]))
            if codes_set is not None and code not in codes_set:
                continue
            amount = float(r.get("成交额", 0) or 0)
            spot_map[code] = {
                "close": float(r["最新价"]),
                "change": float(r.get("涨跌额", 0) or 0),
                "change_pct": float(r["涨跌幅"]),
                "open": float(r.get("今开", 0) or 0),
                "high": float(r.get("最高", 0) or 0),
                "low": float(r.get("最低", 0) or 0),
                "volume": float(r.get("成交量", 0) or 0),
                "amount_yi": round(amount / 1e8, 2),
                "name": str(r["名称"]),
            }
        if codes_set:
            missing = codes_set - set(spot_map.keys())
            if missing:
                logger.warning("实时行情未找到: %s", ", ".join(sorted(missing)))
        return spot_map

    def top_stocks(
        self, stock_df: pd.DataFrame, ascending: bool = False, sort_col: str = "涨跌幅",
    ) -> list[dict]:
        n = self.config.rank_top_n
        sorted_df = stock_df.sort_values(sort_col, ascending=ascending).head(n)
        result = []
        for _, r in sorted_df.iterrows():
            amount = float(r.get("成交额", 0) or 0)
            result.append({
                "code": normalize_code(str(r["代码"])),
                "name": str(r["名称"]),
                "close": float(r["最新价"]),
                "change_pct": float(r["涨跌幅"]),
                "amount": round(amount / 1e8, 2),
            })
        return result

    def market_distribution(self, stock_df: pd.DataFrame) -> list[dict]:
        pct = stock_df["涨跌幅"].astype(float)
        colors = self.config.distribution_colors
        return [
            {"label": "涨停", "count": int((pct >= 9.9).sum()), "color": colors["涨停"]},
            {"label": "涨幅>5%", "count": int(((pct >= 5) & (pct < 9.9)).sum()), "color": colors["涨幅>5%"]},
            {"label": "涨幅0~5%", "count": int(((pct > 0) & (pct < 5)).sum()), "color": colors["涨幅0~5%"]},
            {"label": "平盘", "count": int((pct == 0).sum()), "color": colors["平盘"]},
            {"label": "跌幅0~5%", "count": int(((pct < 0) & (pct > -5)).sum()), "color": colors["跌幅0~5%"]},
            {"label": "跌幅>5%", "count": int(((pct <= -5) & (pct > -9.9)).sum()), "color": colors["跌幅>5%"]},
            {"label": "跌停", "count": int((pct <= -9.9).sum()), "color": colors["跌停"]},
        ]

    def fetch_market_snapshot(self) -> dict[str, Any]:
        from quant_system.utils.time_utils import now_str, today_str

        stock_df = self.fetch_spot_all()
        from quant_system.pipeline.cleaner import clean_spot_df
        stock_df = clean_spot_df(stock_df)

        fund_flow, hsgt_date = self.fetch_fund_flow()
        trade_date = hsgt_date or today_str()

        return {
            "trade_date": trade_date,
            "updated_at": now_str(),
            "indices": self.fetch_indices(),
            "market_distribution": self.market_distribution(stock_df),
            "top_gainers": self.top_stocks(stock_df, ascending=False),
            "top_losers": self.top_stocks(stock_df, ascending=True),
            "top_volume": self.top_stocks(stock_df, ascending=False, sort_col="成交额"),
            "industries": self.fetch_industries(),
            "fund_flow": fund_flow,
        }
