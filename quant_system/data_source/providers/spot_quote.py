"""Per-code quote fallback provider mixin."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import is_eastmoney_disabled, note_eastmoney_failure


class SpotQuoteProviderMixin:
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

    @staticmethod
    def _row_float(row: pd.Series, *keys: str, default: float = 0.0) -> float:
        for key in keys:
            if key in row.index:
                val = row.get(key)
                if val is not None and not pd.isna(val):
                    return float(val)
        return default

    def _spot_from_daily(self, code: str) -> dict[str, Any] | None:
        symbol = to_symbol(code)
        try:
            df, source = self.fetch_daily_hist(symbol)
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            close = self._row_float(r, "收盘", "close")
            if close <= 0:
                return None
            open_ = self._row_float(r, "开盘", "open", default=close)
            high = self._row_float(r, "最高", "high", default=close)
            low = self._row_float(r, "最低", "low", default=close)
            volume = self._row_float(r, "成交量", "volume")
            amount = self._row_float(r, "成交额", "amount")
            prev = self._row_float(df.iloc[-2], "收盘", "close", default=open_) if len(df) >= 2 else open_
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

    def _spot_fallback_sources(self) -> list[str]:
        """逐只行情降级顺序（东财盘口 → 雪球 → 腾讯/新浪日K）。"""
        order: list[str] = []
        if not self.config.disable_eastmoney and not is_eastmoney_disabled():
            order.append("eastmoney")
        for src in [x.strip().lower() for x in self.config.extra_sources.split(",") if x.strip()]:
            if src in ("xueqiu", "tencent") and src not in order:
                order.append(src)
        if "sina" not in order:
            order.append("sina")
        return order

    def _spot_from_xueqiu(self, code: str) -> dict[str, Any] | None:
        try:
            quote = self._xq.fetch_spot_quote(code)
            if quote:
                self.log_ok(f"个股现价 {code}：雪球")
            return quote
        except Exception as e:
            self.log_fail(f"雪球现价 {code}: {e}")
            return None

    def _spot_from_tencent_daily(self, code: str) -> dict[str, Any] | None:
        symbol = to_symbol(code)
        try:
            df = call_with_retry(
                lambda: self.ak.stock_zh_a_hist_tx(symbol=symbol, adjust="qfq"),
                retries=1,
                delay=1.0,
            )
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            close = self._row_float(r, "close", "收盘")
            if close <= 0:
                return None
            open_ = self._row_float(r, "open", "开盘", default=close)
            high = self._row_float(r, "high", "最高", default=close)
            low = self._row_float(r, "low", "最低", default=close)
            volume = self._row_float(r, "volume", "成交量")
            prev = self._row_float(df.iloc[-2], "close", "收盘", default=open_) if len(df) >= 2 else open_
            change = close - prev
            return {
                "close": close,
                "change": round(change, 3),
                "change_pct": round((change / prev * 100) if prev else 0.0, 3),
                "open": open_,
                "high": high,
                "low": low,
                "volume": volume,
                "amount_yi": 0.0,
                "name": "",
                "quote_source": "tencent_daily",
            }
        except Exception as e:
            self.log_fail(f"腾讯日K现价 {code}: {e}")
            return None

    def fetch_spot_quote(self, code: str) -> dict[str, Any] | None:
        """单只股票实时行情（多源降级：东财盘口 → 雪球 → 新浪/腾讯日K）。"""
        code = normalize_code(code)
        for source in self._spot_fallback_sources():
            if source == "eastmoney":
                try:
                    df = call_with_retry(
                        lambda: self.ak.stock_bid_ask_em(symbol=code),
                        retries=1,
                        delay=1.0,
                    )
                    if df is not None and not df.empty:
                        quote = self._parse_bid_ask(code, df)
                        self.log_ok(f"个股盘口 {code}")
                        return quote
                except Exception as e:
                    note_eastmoney_failure(e)
            elif source == "xueqiu":
                quote = self._spot_from_xueqiu(code)
                if quote:
                    return quote
            elif source == "tencent":
                quote = self._spot_from_tencent_daily(code)
                if quote:
                    return quote
            elif source == "sina":
                quote = self._spot_from_daily(code)
                if quote:
                    return quote
        return None
