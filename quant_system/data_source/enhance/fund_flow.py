"""Fund flow enhance provider."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.data_source.enhance.runtime import safe_float
from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.source_guard import is_eastmoney_disabled
from quant_system.utils.time_utils import today_str


class FundFlowProviderMixin:
    def fetch_northbound(self, code: str, days: int = 5) -> tuple[dict[str, Any], list[str]]:
        code = normalize_code(code)
        symbol = to_symbol(code)
        df, err = self._call("northbound", lambda: self.ak.stock_hsgt_individual_em(symbol=symbol))
        if err or not isinstance(df, pd.DataFrame) or df.empty:
            return {}, [err or "northbound"]
        tail = df.tail(days)
        latest = tail.iloc[-1]
        series = []
        for _, r in tail.iterrows():
            hold_value = safe_float(r.get("持股市值"))
            net_buy_amount = safe_float(r.get("今日增持资金"))
            series.append({
                "date": str(r.get("持股日期", ""))[:10],
                "hold_shares": safe_float(r.get("持股数量")),
                "hold_value_yi": round(hold_value / 10000, 2) if hold_value else None,
                "hold_pct": safe_float(r.get("持股数量占A股百分比")),
                "net_buy_shares": safe_float(r.get("今日增持股数")),
                "net_buy_amount_yi": round(net_buy_amount / 10000, 4) if net_buy_amount else None,
            })
        hold_value = safe_float(latest.get("持股市值"))
        net_buy_amount = safe_float(latest.get("今日增持资金"))
        return {
            "trade_date": str(latest.get("持股日期", ""))[:10],
            "hold_shares": safe_float(latest.get("持股数量")),
            "hold_value_yi": round(hold_value / 10000, 2) if hold_value else None,
            "hold_pct": safe_float(latest.get("持股数量占A股百分比")),
            "net_buy_shares": safe_float(latest.get("今日增持股数")),
            "net_buy_amount_yi": round(net_buy_amount / 10000, 4) if net_buy_amount else None,
            "series": series,
            "source": "hsgt_individual",
        }, []

    @staticmethod
    def _margin_markets(code: str) -> list[str]:
        if code.startswith(("6", "5", "9")):
            return ["sse"]
        return ["szse"]

    def fetch_margin(self, code: str) -> tuple[dict[str, Any] | None, list[str]]:
        if self._is_disabled("margin_probe"):
            return None, ["margin"]
        code = normalize_code(code)
        from quant_system.utils.trade_calendar import get_calendar

        cal = get_calendar()
        probe_dates: list[str] = []
        d = today_str()
        for _ in range(3):
            probe_dates.append(d.replace("-", ""))
            prev = cal.prev_trade_day(d)
            if not prev:
                break
            d = prev

        failed: list[str] = []
        for date in probe_dates:
            fetchers = [
                (market, lambda dt=date, m=market: (
                    self.ak.stock_margin_detail_sse(date=dt)
                    if m == "sse" else self.ak.stock_margin_detail_szse(date=dt)
                ))
                for market in self._margin_markets(code)
            ]
            for market, fn in fetchers:
                df, err = self._call(f"margin_{market}", fn)
                if err:
                    failed.append(err)
                    continue
                if not isinstance(df, pd.DataFrame) or df.empty:
                    continue
                col = "标的证券代码" if "标的证券代码" in df.columns else None
                if not col:
                    continue
                sub = df[df[col].astype(str).map(normalize_code) == code]
                if sub.empty:
                    continue
                r = sub.iloc[0]
                margin_balance = safe_float(r.get("融资余额"))
                margin_buy = safe_float(r.get("融资买入额"))
                return {
                    "trade_date": str(r.get("信用交易日期", date))[:10],
                    "margin_balance_yi": round(margin_balance / 1e8, 2) if margin_balance else None,
                    "margin_buy_yi": round(margin_buy / 1e8, 2) if margin_buy else None,
                    "short_balance": safe_float(r.get("融券余量")),
                    "source": market,
                }, []
        if failed:
            self._disable("margin_probe")
        return None, failed[:1] if failed else ["margin"]

    def fetch_market_fund_flow(self) -> dict[str, Any]:
        from quant_system.data_source.eastmoney import EastMoneyCrawler

        if is_eastmoney_disabled():
            return {"trade_date": None, "north_net": 0.0, "main_net": 0.0, "retail_net": 0.0}
        flow, trade_date = EastMoneyCrawler(self.config).fetch_fund_flow()
        return {"trade_date": trade_date, **flow}
