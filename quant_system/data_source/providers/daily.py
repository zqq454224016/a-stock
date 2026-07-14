"""Daily K-line provider mixin."""

from __future__ import annotations

import pandas as pd

from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import is_eastmoney_disabled, note_eastmoney_failure


class DailyProviderMixin:
    def fetch_daily_hist(self, symbol: str, adjust: str = "qfq") -> tuple[pd.DataFrame, str]:
        """拉取日 K，返回 (DataFrame, source)。日 K 优先东财（通常含当日）。"""
        code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        if not is_eastmoney_disabled():
            try:
                df = call_with_retry(
                    lambda: self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust),
                    retries=1,
                    delay=1.0,
                )
                if df is not None and not df.empty:
                    self.log_ok(f"日K {symbol}：东财 {len(df)} 条")
                    return df, "eastmoney"
            except Exception as e:
                note_eastmoney_failure(e)

        try:
            df = call_with_retry(
                lambda: self.ak.stock_zh_a_daily(symbol=symbol, adjust=adjust),
                retries=1,
                delay=1.0,
            )
            self.log_ok(f"日K {symbol}：新浪 {len(df)} 条")
            return df, "sina"
        except Exception as e:
            self.log_fail(f"新浪日K不可用: {e}")

        df = call_with_retry(
            lambda: self.ak.stock_zh_a_hist_tx(symbol=symbol, adjust=adjust),
            retries=1,
            delay=1.0,
        )
        self.log_ok(f"日K {symbol}：腾讯 {len(df)} 条")
        return df, "tencent"

    def fetch_daily_hist_source(self, symbol: str, source: str, adjust: str = "qfq") -> pd.DataFrame:
        """按指定来源拉取日 K（用于跨源校验）。"""
        code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        if source == "eastmoney":
            if is_eastmoney_disabled():
                raise RuntimeError("eastmoney disabled")
            return call_with_retry(
                lambda: self.ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adjust),
                retries=1,
                delay=1.0,
            )
        if source == "sina":
            return self._retry(lambda: self.ak.stock_zh_a_daily(symbol=symbol, adjust=adjust))
        if source == "tencent":
            return self._retry(lambda: self.ak.stock_zh_a_hist_tx(symbol=symbol, adjust=adjust))
        raise ValueError(f"未知日K来源: {source}")
