"""P1-3 数据增强采集（估值/公司行为/资金/指数）。"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.base_crawler import BaseCrawler
from quant_system.pipeline.normalizer import normalize_code, to_symbol
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import today_str

logger = get_logger(__name__)


def _safe_float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _latest_row(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    return df.iloc[-1]


class EnhanceAPI(BaseCrawler):
    """个股增强数据：估值、公司行为、北向/两融、指数对照。"""

    source_name = "enhance"

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

    def _call(self, label: str, fn: Callable, *args, **kwargs) -> tuple[Any | None, str | None]:
        try:
            return self._retry(fn, *args, **kwargs), None
        except Exception as e:
            msg = f"{label}: {e}"
            self.log_fail(msg)
            return None, label

    def fetch_valuation(self, code: str) -> tuple[dict[str, Any], list[str]]:
        code = normalize_code(code)
        failed: list[str] = []
        out: dict[str, Any] = {"source": None}

        df, err = self._call("valuation_em", lambda: self.ak.stock_value_em(symbol=code))
        if err:
            failed.append(err)
        row = _latest_row(df) if isinstance(df, pd.DataFrame) else None
        if row is not None:
            out.update({
                "trade_date": str(row.get("数据日期", ""))[:10],
                "close": _safe_float(row.get("当日收盘价")),
                "market_cap_yi": round(_safe_float(row.get("总市值")) / 1e8, 2)
                if _safe_float(row.get("总市值")) else None,
                "float_cap_yi": round(_safe_float(row.get("流通市值")) / 1e8, 2)
                if _safe_float(row.get("流通市值")) else None,
                "pe_ttm": _safe_float(row.get("PE(TTM)")),
                "pe_static": _safe_float(row.get("PE(静)")),
                "pb": _safe_float(row.get("市净率")),
                "ps": _safe_float(row.get("市销率")),
                "peg": _safe_float(row.get("PEG值")),
                "source": "eastmoney_value",
            })
            return out, failed

        pe_df, err = self._call(
            "valuation_baidu_pe",
            lambda: self.ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)"),
        )
        if err:
            failed.append(err)
        pe_row = _latest_row(pe_df) if isinstance(pe_df, pd.DataFrame) else None
        if pe_row is not None:
            out["pe_ttm"] = _safe_float(pe_row.get("value"))
            out["trade_date"] = str(pe_row.get("date", today_str()))[:10]
            out["source"] = "baidu_pe"

        pb_df, err = self._call(
            "valuation_baidu_pb",
            lambda: self.ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率"),
        )
        if err:
            failed.append(err)
        pb_row = _latest_row(pb_df) if isinstance(pb_df, pd.DataFrame) else None
        if pb_row is not None:
            out["pb"] = _safe_float(pb_row.get("value"))
            if not out.get("source"):
                out["source"] = "baidu_pb"
            if not out.get("trade_date"):
                out["trade_date"] = str(pb_row.get("date", today_str()))[:10]

        info_df, err = self._call("individual_info", lambda: self.ak.stock_individual_info_em(symbol=code))
        if err:
            failed.append(err)
        if isinstance(info_df, pd.DataFrame) and not info_df.empty:
            info = dict(zip(info_df["item"].astype(str), info_df["value"]))
            out.setdefault("market_cap_yi", _safe_float(info.get("总市值")))
            out.setdefault("float_cap_yi", _safe_float(info.get("流通市值")))
            out.setdefault("pe_ttm", _safe_float(info.get("市盈率-动态") or info.get("市盈率")))
            out.setdefault("pb", _safe_float(info.get("市净率")))
            if not out.get("source"):
                out["source"] = "eastmoney_info"

        return out, failed

    def fetch_dividends(self, code: str, limit: int = 5) -> tuple[list[dict[str, Any]], list[str]]:
        code = normalize_code(code)
        df, err = self._call(
            "dividend",
            lambda: self.ak.stock_history_dividend_detail(symbol=code, indicator="分红"),
        )
        if err or not isinstance(df, pd.DataFrame) or df.empty:
            return [], [err or "dividend"]
        rows: list[dict[str, Any]] = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "announce_date": str(r.get("公告日期", ""))[:10],
                "ex_date": str(r.get("除权除息日", ""))[:10],
                "record_date": str(r.get("股权登记日", ""))[:10],
                "cash_div": _safe_float(r.get("派息")),
                "bonus_ratio": _safe_float(r.get("送股")),
                "transfer_ratio": _safe_float(r.get("转增")),
                "status": str(r.get("进度", "")),
            })
        return rows, []

    def fetch_lockup(self, code: str, limit: int = 3) -> tuple[list[dict[str, Any]], list[str]]:
        code = normalize_code(code)
        df, err = self._call(
            "lockup",
            lambda: self.ak.stock_restricted_release_queue_em(symbol=code),
        )
        if err or not isinstance(df, pd.DataFrame) or df.empty:
            return [], [err or "lockup"]
        rows: list[dict[str, Any]] = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "unlock_date": str(r.get("解禁时间", ""))[:10],
                "unlock_shares": _safe_float(r.get("实际解禁数量")),
                "unlock_value_yi": round(_safe_float(r.get("实际解禁数量市值")) / 1e8, 2)
                if _safe_float(r.get("实际解禁数量市值")) else None,
                "pct_total": _safe_float(r.get("占总市值比例")),
                "pct_float": _safe_float(r.get("占流通市值比例")),
                "holder_type": str(r.get("限售股类型", "")),
            })
        return rows, []

    def fetch_earnings_forecast(self, code: str) -> tuple[dict[str, Any] | None, list[str]]:
        code = normalize_code(code)
        year = int(today_str()[:4])
        dates = []
        for y in (year, year - 1):
            for md in ("1231", "0930", "0630", "0331"):
                dates.append(f"{y}{md}")
        failed: list[str] = []
        for d in dates:
            df, err = self._call(f"earnings_forecast_{d}", lambda date=d: self.ak.stock_yjyg_em(date=date))
            if err:
                failed.append(err)
                continue
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            sub = df[df["股票代码"].astype(str).map(normalize_code) == code]
            if sub.empty:
                continue
            r = sub.iloc[0]
            return {
                "indicator": str(r.get("预测指标", "")),
                "forecast_type": str(r.get("预告类型", "")),
                "change_pct": _safe_float(r.get("业绩变动幅度")),
                "forecast_value": str(r.get("预测数值", "")),
                "reason": str(r.get("业绩变动原因", ""))[:200],
                "announce_date": str(r.get("公告日期", ""))[:10],
                "report_period": d,
            }, failed[:1]
        return None, failed[:1] if failed else ["earnings_forecast"]

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
            series.append({
                "date": str(r.get("持股日期", ""))[:10],
                "hold_shares": _safe_float(r.get("持股数量")),
                "hold_value_yi": round(_safe_float(r.get("持股市值")) / 10000, 2)
                if _safe_float(r.get("持股市值")) else None,
                "hold_pct": _safe_float(r.get("持股数量占A股百分比")),
                "net_buy_shares": _safe_float(r.get("今日增持股数")),
                "net_buy_amount_yi": round(_safe_float(r.get("今日增持资金")) / 10000, 4)
                if _safe_float(r.get("今日增持资金")) else None,
            })
        return {
            "trade_date": str(latest.get("持股日期", ""))[:10],
            "hold_shares": _safe_float(latest.get("持股数量")),
            "hold_value_yi": round(_safe_float(latest.get("持股市值")) / 10000, 2)
            if _safe_float(latest.get("持股市值")) else None,
            "hold_pct": _safe_float(latest.get("持股数量占A股百分比")),
            "net_buy_shares": _safe_float(latest.get("今日增持股数")),
            "net_buy_amount_yi": round(_safe_float(latest.get("今日增持资金")) / 10000, 4)
            if _safe_float(latest.get("今日增持资金")) else None,
            "series": series,
            "source": "hsgt_individual",
        }, []

    def fetch_margin(self, code: str) -> tuple[dict[str, Any] | None, list[str]]:
        code = normalize_code(code)
        from quant_system.utils.trade_calendar import get_calendar

        cal = get_calendar()
        probe_dates = []
        d = today_str()
        for _ in range(8):
            probe_dates.append(d.replace("-", ""))
            prev = cal.prev_trade_day(d)
            if not prev:
                break
            d = prev

        for date in probe_dates:
            fetchers = [
                ("sse", lambda dt=date: self.ak.stock_margin_detail_sse(date=dt)),
                ("szse", lambda dt=date: self.ak.stock_margin_detail_szse(date=dt)),
            ]
            for market, fn in fetchers:
                df, err = self._call(f"margin_{market}", fn)
                if err or not isinstance(df, pd.DataFrame) or df.empty:
                    continue
                col = "标的证券代码" if "标的证券代码" in df.columns else None
                if not col:
                    continue
                sub = df[df[col].astype(str).map(normalize_code) == code]
                if sub.empty:
                    continue
                r = sub.iloc[0]
                return {
                    "trade_date": str(r.get("信用交易日期", date))[:10],
                    "margin_balance_yi": round(_safe_float(r.get("融资余额")) / 1e8, 2)
                    if _safe_float(r.get("融资余额")) else None,
                    "margin_buy_yi": round(_safe_float(r.get("融资买入额")) / 1e8, 2)
                    if _safe_float(r.get("融资买入额")) else None,
                    "short_balance": _safe_float(r.get("融券余量")),
                    "source": market,
                }, []
        return None, ["margin"]

    def fetch_market_fund_flow(self) -> dict[str, Any]:
        from quant_system.data_source.eastmoney import EastMoneyCrawler
        flow, trade_date = EastMoneyCrawler(self.config).fetch_fund_flow()
        return {"trade_date": trade_date, **flow}
