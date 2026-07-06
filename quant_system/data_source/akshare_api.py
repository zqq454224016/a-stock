"""AkShare 数据源（多接口封装 + 自动降级）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.data_source.eastmoney import EastMoneyCrawler
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, to_symbol
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry

logger = get_logger(__name__)


class AkShareAPI(BaseCrawler):
    source_name = "akshare"

    def __init__(self, config: CrawlerConfig | None = None):
        super().__init__(config)
        self._ak = None
        self._em = EastMoneyCrawler(config)
        self._eastmoney_disabled = False

    @property
    def ak(self):
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def _try_eastmoney(self, fn, label: str):
        """尝试东财接口；失败一次后本会话内不再重试东财（仅用于非行情类探测）。"""
        if self._eastmoney_disabled:
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

    def _spot_source_order(self) -> list[str]:
        prefer = self.config.prefer_source
        if prefer == "eastmoney":
            return ["eastmoney", "sina", "eastmoney_direct"]
        if prefer == "sina":
            return ["sina", "eastmoney", "eastmoney_direct"]
        return ["eastmoney", "sina", "eastmoney_direct"]

    def _fetch_spot_source(self, source: str) -> pd.DataFrame:
        if source == "eastmoney":
            return call_with_retry(
                self._em.fetch_spot_all,
                retries=self.config.eastmoney_probe_retries,
                delay=self.config.retry_delay,
            )
        if source == "sina":
            return call_with_retry(
                self.ak.stock_zh_a_spot,
                retries=2,
                delay=self.config.retry_delay,
            )
        if source == "eastmoney_direct":
            return call_with_retry(
                self.ak.stock_zh_a_spot_em,
                retries=self.config.eastmoney_probe_retries,
                delay=self.config.retry_delay,
            )
        raise ValueError(f"未知行情源: {source}")

    def fetch_spot_all(self) -> pd.DataFrame:
        errors: list[str] = []
        for source in self._spot_source_order():
            try:
                df = self._fetch_spot_source(source)
                if df is not None and not df.empty:
                    label = {"eastmoney": "东财", "sina": "新浪", "eastmoney_direct": "东财直连"}[source]
                    self.log_ok(f"个股快照：{label} {len(df)} 只")
                    return df
            except Exception as e:
                errors.append(f"{source}: {e}")
                self.log_fail(f"个股快照 {source} 失败: {e}")
        raise RuntimeError(f"全市场行情不可用: {'; '.join(errors)}")

    def _quotes_to_spot_df(self, spot_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for code, q in spot_map.items():
            if q.get("close") is None:
                continue
            rows.append({
                "代码": code,
                "名称": q.get("name") or code,
                "最新价": float(q["close"]),
                "涨跌额": float(q.get("change", 0) or 0),
                "涨跌幅": float(q.get("change_pct", 0) or 0),
                "今开": float(q.get("open", 0) or 0),
                "最高": float(q.get("high", 0) or 0),
                "最低": float(q.get("low", 0) or 0),
                "成交量": float(q.get("volume", 0) or 0),
                "成交额": float(q.get("amount_yi", 0) or 0) * 1e8,
            })
        return pd.DataFrame(rows)

    def _spot_df_from_stocks_cache(self, store: Any) -> pd.DataFrame:
        spot_map: dict[str, dict[str, Any]] = {}
        for item in load_watchlist(self.config):
            code = normalize_code(item["code"])
            path = store.config.json_data_dir / "stocks" / f"{code}.json"
            if not path.exists():
                continue
            data = store.read(path)
            quote = data.get("quote") or {}
            if quote.get("close") is None:
                continue
            spot_map[code] = {**quote, "name": data.get("name", quote.get("name", ""))}
        return self._quotes_to_spot_df(spot_map)

    def _resolve_market_spot_df(self, store: Any, limitations: list[str]) -> tuple[pd.DataFrame, str]:
        from quant_system.pipeline.cleaner import clean_spot_df

        try:
            df = clean_spot_df(self.fetch_spot_all())
            if not df.empty:
                return df, "full_market"
        except Exception as e:
            limitations.append("bulk_spot_failed")
            logger.warning("全市场行情失败，降级自选股: %s", e)

        codes = [normalize_code(x["code"]) for x in load_watchlist(self.config)]
        if codes:
            spot_map = self.fetch_spot_map(codes=codes)
            df = self._quotes_to_spot_df(spot_map)
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

    def _parse_bid_ask(self, code: str, df: pd.DataFrame) -> dict[str, Any]:
        mapping = dict(zip(df["item"].astype(str), df["value"]))
        close = float(mapping.get("最新", 0) or 0)
        if close <= 0:
            raise ValueError("盘口无有效现价")
        amount = float(mapping.get("金额", 0) or 0)
        volume = float(mapping.get("总手", 0) or 0)
        return {
            "close": close,
            "change": float(mapping.get("涨跌", 0) or 0),
            "change_pct": float(mapping.get("涨幅", 0) or 0),
            "open": float(mapping.get("今开", 0) or 0),
            "high": float(mapping.get("最高", 0) or 0),
            "low": float(mapping.get("最低", 0) or 0),
            "volume": volume,
            "amount_yi": round(amount / 1e8, 2),
            "name": "",
            "quote_source": "bid_ask",
        }

    def _spot_from_daily(self, code: str) -> dict[str, Any] | None:
        symbol = to_symbol(code)
        try:
            df, source = self.fetch_daily_hist(symbol)
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            close = float(r.get("收盘", r.get("close", 0)) or 0)
            if close <= 0:
                return None
            open_ = float(r.get("开盘", r.get("open", close)) or close)
            high = float(r.get("最高", r.get("high", close)) or close)
            low = float(r.get("最低", r.get("low", close)) or close)
            volume = float(r.get("成交量", r.get("volume", 0)) or 0)
            amount = float(r.get("成交额", 0) or 0)
            prev = float(df.iloc[-2]["收盘"]) if len(df) >= 2 else open_
            change = close - prev
            change_pct = (change / prev * 100) if prev else 0.0
            return {
                "close": close,
                "change": round(change, 3),
                "change_pct": round(change_pct, 3),
                "open": open_,
                "high": high,
                "low": low,
                "volume": volume,
                "amount_yi": round(amount / 1e8, 2) if amount else 0.0,
                "name": "",
                "quote_source": f"daily_{source}",
            }
        except Exception as e:
            self.log_fail(f"日K降级行情 {code}: {e}")
            return None

    def fetch_spot_quote(self, code: str) -> dict[str, Any] | None:
        """单只股票实时行情（盘口 → 日 K 降级）。"""
        code = normalize_code(code)
        try:
            df = call_with_retry(
                lambda: self.ak.stock_bid_ask_em(symbol=code),
                retries=2,
                delay=self.config.retry_delay,
            )
            if df is not None and not df.empty:
                quote = self._parse_bid_ask(code, df)
                self.log_ok(f"个股盘口 {code}")
                return quote
        except Exception as e:
            self.log_fail(f"盘口 {code}: {e}")
        return self._spot_from_daily(code)

    def _spot_row_to_quote(self, r: pd.Series) -> dict[str, Any]:
        amount = float(r.get("成交额", 0) or 0)
        return {
            "close": float(r["最新价"]),
            "change": float(r.get("涨跌额", 0) or 0),
            "change_pct": float(r["涨跌幅"]),
            "open": float(r.get("今开", 0) or 0),
            "high": float(r.get("最高", 0) or 0),
            "low": float(r.get("最低", 0) or 0),
            "volume": float(r.get("成交量", 0) or 0),
            "amount_yi": round(amount / 1e8, 2),
            "name": str(r["名称"]),
            "quote_source": "bulk_spot",
        }

    def fetch_spot_map(self, codes: list[str] | None = None) -> dict[str, dict]:
        """全市场或指定代码的实时快照；失败时对小范围自选股逐只降级。"""
        codes_set = {normalize_code(c) for c in codes} if codes else None
        use_watchlist_fallback = codes_set is not None and len(codes_set) <= self.config.watchlist_spot_threshold

        if codes_set and len(codes_set) <= 10:
            logger.info("自选股 %s 只，拉取实时行情…", len(codes_set))
        else:
            logger.info("拉取全市场实时行情…")

        spot_map: dict[str, dict] = {}
        bulk_ok = False
        try:
            df = self.fetch_spot_all()
            bulk_ok = True
            for _, r in df.iterrows():
                code = normalize_code(str(r["代码"]))
                if codes_set is not None and code not in codes_set:
                    continue
                spot_map[code] = self._spot_row_to_quote(r)
        except Exception as e:
            logger.warning("全市场行情失败: %s", e)
            if not use_watchlist_fallback:
                raise

        if codes_set:
            missing = codes_set - set(spot_map.keys())
            if missing:
                logger.warning("实时行情未找到 %s 只，尝试逐只拉取: %s", len(missing), ", ".join(sorted(missing)))
                for code in sorted(missing):
                    quote = self.fetch_spot_quote(code)
                    if quote:
                        spot_map[code] = quote
            still_missing = codes_set - set(spot_map.keys())
            if still_missing:
                logger.warning("实时行情仍缺失: %s", ", ".join(sorted(still_missing)))
            elif not bulk_ok:
                logger.info("自选股行情已通过逐只降级获取 %s 只", len(spot_map))
        return spot_map

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
