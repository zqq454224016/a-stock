"""东方财富数据源。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.utils.retry import call_with_retry


class EastMoneyCrawler(BaseCrawler):
    source_name = "eastmoney"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def fetch_spot_all(self) -> pd.DataFrame:
        return self._retry(self.ak.stock_zh_a_spot_em)

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        return self._retry(
            lambda: self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust)
        )

    def fetch_indices(self) -> list[dict[str, Any]]:
        index_df = self._retry(self.ak.stock_zh_index_spot_em)
        indices = []
        for code, name in self.config.index_map_em.items():
            row = index_df[index_df["代码"] == code]
            if row.empty:
                continue
            r = row.iloc[0]
            indices.append({
                "name": name, "code": code,
                "close": float(r["最新价"]),
                "change": float(r["涨跌额"]),
                "change_pct": float(r["涨跌幅"]),
            })
        self.log_ok(f"指数 {len(indices)} 个")
        return indices

    def fetch_industries(self) -> list[dict[str, Any]]:
        industry_df = self._retry(self.ak.stock_board_industry_name_em)
        industries = [
            {"name": str(r["板块名称"]), "change_pct": float(r["涨跌幅"])}
            for _, r in industry_df.head(self.config.industry_top_n).iterrows()
        ]
        self.log_ok(f"行业 {len(industries)} 个")
        return industries

    def fetch_fund_flow(self) -> tuple[dict[str, float], str | None]:
        fund_flow = {"north_net": 0.0, "main_net": 0.0, "retail_net": 0.0}
        trade_date = None

        try:
            summary_df = call_with_retry(
                self.ak.stock_hsgt_fund_flow_summary_em,
                retries=1,
                delay=self.config.retry_delay,
            )
            north = summary_df[summary_df["资金方向"] == "北向"]
            if not north.empty:
                fund_flow["north_net"] = round(float(north["成交净买额"].sum()), 2)
            trade_date = str(summary_df.iloc[0]["交易日"])
        except Exception as e:
            self.log_fail(f"北向资金不可用: {e}")

        try:
            industry_df = call_with_retry(
                lambda: self.ak.stock_fund_flow_industry(symbol="即时"),
                retries=1,
                delay=self.config.retry_delay,
            )
            fund_flow["main_net"] = round(float(industry_df["净额"].astype(float).sum()), 2)
        except Exception as e:
            self.log_fail(f"主力资金不可用: {e}")

        return fund_flow, trade_date
