"""Market snapshot assembly provider mixin."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class SnapshotProviderMixin:
    def _resolve_market_spot_df(self, store: Any, limitations: list[str]) -> tuple[pd.DataFrame, str]:
        from quant_system.pipeline.cleaner import clean_spot_df

        codes = [normalize_code(x["code"]) for x in load_watchlist(self.config)]
        if codes and self._should_skip_bulk_spot(set(codes)):
            logger.info("自选股 %s 只，跳过全市场行情，逐只拉取", len(codes))
            limitations.append("bulk_spot_skipped")
            spot_map = self._fetch_spot_map_per_code(codes)
            if spot_map:
                df = clean_spot_df(self._quotes_to_spot_df(spot_map))
                if not df.empty:
                    limitations.append("spot_watchlist_only")
                    return df, "watchlist"

        try:
            df = clean_spot_df(self.fetch_spot_all())
            if not df.empty:
                return df, "full_market"
        except Exception as e:
            limitations.append("bulk_spot_failed")
            logger.warning("全市场行情失败，降级自选股: %s", e)

        if codes:
            spot_map = self._fetch_spot_map_per_code(codes)
            df = clean_spot_df(self._quotes_to_spot_df(spot_map))
            if not df.empty:
                limitations.append("spot_watchlist_only")
                return df, "watchlist"

        df = self._spot_df_from_stocks_cache(store)
        if not df.empty:
            limitations.append("spot_stock_cache")
            return df, "stock_cache"

        return pd.DataFrame(), "none"

    def _cached_market(self, store: Any) -> dict[str, Any]:
        path = store.config.json_data_dir / "latest.json"
        if path.exists():
            return store.read(path)
        return {}

    def _safe_indices(self, cached: dict[str, Any], limitations: list[str]) -> list[dict[str, Any]]:
        try:
            indices = self.fetch_indices()
            if indices:
                return indices
        except Exception as e:
            logger.warning("指数采集失败: %s", e)
            limitations.append("indices_failed")
        return list(cached.get("indices") or [])

    def _safe_industries(self, cached: dict[str, Any], limitations: list[str]) -> list[dict[str, Any]]:
        try:
            return self.fetch_industries()
        except Exception as e:
            logger.warning("行业采集失败: %s", e)
            limitations.append("industries_failed")
        return list(cached.get("industries") or [])

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

    def fetch_market_snapshot(self, store: Any | None = None) -> dict[str, Any]:
        from quant_system.config.db_config import DBConfig
        from quant_system.storage.json_store import JsonStore
        from quant_system.utils.time_utils import now_str, today_str

        store = store or JsonStore(DBConfig())
        cached = self._cached_market(store)
        limitations: list[str] = []

        stock_df, spot_scope = self._resolve_market_spot_df(store, limitations)
        fund_flow, hsgt_date = self.fetch_fund_flow()
        trade_date = hsgt_date or cached.get("trade_date") or today_str()

        indices = self._safe_indices(cached, limitations)
        industries = self._safe_industries(cached, limitations)

        if stock_df.empty:
            top_gainers = list(cached.get("top_gainers") or [])
            top_losers = list(cached.get("top_losers") or [])
            top_volume = list(cached.get("top_volume") or [])
            distribution = list(cached.get("market_distribution") or [])
            if not top_gainers:
                limitations.append("spot_unavailable")
        else:
            top_gainers = self.top_stocks(stock_df, ascending=False)
            top_losers = self.top_stocks(stock_df, ascending=True)
            top_volume = self.top_stocks(stock_df, ascending=False, sort_col="成交额")
            distribution = self.market_distribution(stock_df)

        if not fund_flow or all(v == 0 for v in fund_flow.values()):
            fund_flow = dict(cached.get("fund_flow") or fund_flow)

        return {
            "trade_date": trade_date,
            "updated_at": now_str(),
            "indices": indices,
            "market_distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "top_volume": top_volume,
            "industries": industries,
            "fund_flow": fund_flow,
            "spot_scope": spot_scope,
            "degraded": bool(limitations),
            "limitations": limitations,
        }
