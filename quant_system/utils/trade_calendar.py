"""A 股交易日历。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import today_str

logger = get_logger(__name__)


class TradeCalendar:
    """A 股交易日历（新浪数据源，本地 JSON 缓存）。"""

    def __init__(self, cache_path: Path | None = None):
        cfg = DBConfig()
        self.cache_path = cache_path or (cfg.json_data_dir / "calendar" / "trade_dates.json")

    def _load_cache(self) -> list[str] | None:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            dates = data.get("dates", [])
            return [str(d) for d in dates] if dates else None
        except Exception as e:
            logger.warning("读取交易日历缓存失败: %s", e)
            return None

    def _save_cache(self, dates: list[str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": "sina",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(dates),
            "dates": dates,
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("交易日历已缓存 %s 条 -> %s", len(dates), self.cache_path)

    def fetch_dates(self, force_refresh: bool = False) -> list[str]:
        if not force_refresh:
            cached = self._load_cache()
            if cached:
                return cached

        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            col = "trade_date" if "trade_date" in df.columns else df.columns[0]
            dates = sorted({
                (d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10])
                for d in df[col].tolist()
            })
            self._save_cache(dates)
            return dates
        except Exception as e:
            logger.error("拉取交易日历失败: %s", e)
            cached = self._load_cache()
            if cached:
                logger.warning("使用过期交易日历缓存")
                return cached
            raise

    def _dates_set(self) -> set[str]:
        return set(self.fetch_dates())

    def is_trade_day(self, d: str | date | None = None) -> bool:
        if d is None:
            d = today_str()
        ds = d.strftime("%Y-%m-%d") if isinstance(d, date) else str(d)[:10]
        return ds in self._dates_set()

    def latest_trade_day(self, on_or_before: str | date | None = None) -> str:
        """返回 on_or_before 当日或之前最近的一个交易日。"""
        if on_or_before is None:
            on_or_before = today_str()
        target = on_or_before.strftime("%Y-%m-%d") if isinstance(on_or_before, date) else str(on_or_before)[:10]
        dates = [d for d in self.fetch_dates() if d <= target]
        if not dates:
            raise ValueError(f"交易日历中无 <= {target} 的日期")
        return dates[-1]

    def trade_days_between(self, start: str, end: str) -> list[str]:
        start, end = start[:10], end[:10]
        return [d for d in self.fetch_dates() if start <= d <= end]

    def prev_trade_day(self, d: str | date) -> str | None:
        ds = d.strftime("%Y-%m-%d") if isinstance(d, date) else str(d)[:10]
        prior = [x for x in self.fetch_dates() if x < ds]
        return prior[-1] if prior else None

    def next_trade_day(self, d: str | date) -> str | None:
        ds = d.strftime("%Y-%m-%d") if isinstance(d, date) else str(d)[:10]
        later = [x for x in self.fetch_dates() if x > ds]
        return later[0] if later else None

    def expected_trading_dates(self, start: str, end: str) -> list[str]:
        return self.trade_days_between(start, end)


@lru_cache(maxsize=1)
def get_calendar() -> TradeCalendar:
    return TradeCalendar()
