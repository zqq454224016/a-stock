"""同花顺数据源（行业/估值/盈利预测）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.i18n_labels import humanize_fetch_error
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import is_ths_disabled, note_ths_failure
from quant_system.utils.time_utils import today_str

logger = get_logger(__name__)


class TonghuashunCrawler(BaseCrawler):
    source_name = "同花顺"

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
        raise NotImplementedError

    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> pd.DataFrame:
        raise NotImplementedError

    def _call(self, label: str, fn):
        if is_ths_disabled():
            raise RuntimeError("ths disabled")
        try:
            return call_with_retry(fn, retries=1, delay=1.0)
        except Exception as e:
            note_ths_failure(e)
            raise RuntimeError(f"{label}: {humanize_fetch_error(e)}") from e

    def fetch_industries(self) -> list[dict[str, Any]]:
        df = self._call("industry_summary", self.ak.stock_board_industry_summary_ths)
        industries = [
            {"name": str(r["板块"]), "change_pct": float(r["涨跌幅"])}
            for _, r in df.head(self.config.industry_top_n).iterrows()
        ]
        self.log_ok(f"行业 {len(industries)} 个")
        return industries

    def fetch_valuation(self, code: str) -> dict[str, Any]:
        """从同花顺财务摘要提取 PE/PB（若字段存在）。"""
        code = normalize_code(code)
        df = self._call(
            "financial_abstract",
            lambda: self.ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期"),
        )
        if df is None or df.empty:
            return {}
        latest = df.iloc[-1]
        out: dict[str, Any] = {
            "trade_date": str(latest.get("报告期", today_str()))[:10],
            "source": "ths_financial",
        }
        for col in latest.index:
            name = str(col)
            if "市盈率" in name and out.get("pe_ttm") is None:
                try:
                    out["pe_ttm"] = float(latest[col])
                except (TypeError, ValueError):
                    pass
            if "市净率" in name and out.get("pb") is None:
                try:
                    out["pb"] = float(latest[col])
                except (TypeError, ValueError):
                    pass
        return out

    def fetch_earnings_forecast(self, code: str) -> dict[str, Any] | None:
        code = normalize_code(code)
        df = self._call(
            "profit_forecast",
            lambda: self.ak.stock_profit_forecast_ths(symbol=code, indicator="预测年报每股收益"),
        )
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        year_cols = [c for c in df.columns if str(c).isdigit() or "预测" in str(c)]
        value = None
        for col in reversed(year_cols):
            try:
                value = float(row[col])
                break
            except (TypeError, ValueError):
                continue
        return {
            "indicator": "预测年报每股收益",
            "forecast_type": "机构预测",
            "forecast_value": str(value) if value is not None else str(row.iloc[-1]),
            "announce_date": today_str(),
            "report_period": str(df.columns[-1])[:4] if len(df.columns) else today_str()[:4],
            "source": "ths_profit_forecast",
        }
