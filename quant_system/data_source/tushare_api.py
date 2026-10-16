"""Minimal Tushare Pro HTTP adapter for missing point-in-time market facts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from urllib.request import Request, urlopen

from quant_system.config.crawler_config import CrawlerConfig


class TushareAPI:
    name = "tushare"
    endpoint = "https://api.tushare.pro"

    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()
        if not self.config.tushare_token:
            raise RuntimeError("未配置 Tushare Token")

    def query(self, api_name: str, *, fields: str = "", **params: Any) -> list[dict[str, Any]]:
        body = json.dumps({
            "api_name": api_name,
            "token": self.config.tushare_token,
            "params": {key: value for key, value in params.items() if value not in (None, "")},
            "fields": fields,
        }).encode("utf-8")
        request = Request(self.endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.config.request_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != 0:
            raise RuntimeError(f"Tushare {api_name} 失败: {payload.get('msg') or payload.get('code')}")
        data = payload.get("data") or {}
        fields_list = data.get("fields") or []
        return [dict(zip(fields_list, row)) for row in data.get("items") or []]

    def query_all(self, api_name: str, *, fields: str = "", page_size: int = 1000, **params: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.query(api_name, fields=fields, limit=page_size, offset=offset, **params)
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size

    def fetch_latest_ex_factors(self, lookback_days: int = 10) -> list[dict[str, Any]]:
        for offset in range(lookback_days + 1):
            trade_date = (date.today() - timedelta(days=offset)).strftime("%Y%m%d")
            rows = self.query("adj_factor", trade_date=trade_date, fields="ts_code,trade_date,adj_factor")
            if rows:
                return [{
                    "symbol": row["ts_code"],
                    "trade_date": f"{row['trade_date'][:4]}-{row['trade_date'][4:6]}-{row['trade_date'][6:8]}",
                    "ex_factor": float(row["adj_factor"]),
                    "source": self.name,
                } for row in rows]
        return []

    def fetch_market_status(self, trade_date: str) -> dict[str, Any]:
        requested = date.fromisoformat(trade_date)
        start = (requested - timedelta(days=14)).strftime("%Y%m%d")
        end = requested.strftime("%Y%m%d")
        try:
            calendar = self.query(
                "trade_cal", exchange="SSE", start_date=start, end_date=end, is_open="1",
                fields="exchange,cal_date,is_open,pretrade_date",
            )
            available = sorted((str(row.get("cal_date")) for row in calendar if row.get("cal_date")), reverse=True)
            compact = available[0] if available else end
        except Exception:
            compact = end
        actual_date = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        result: dict[str, Any] = {"source": self.name, "trade_date": actual_date, "requested_date": trade_date, "errors": {}}
        calls = {
            "suspended": ("suspend_d", {"trade_date": compact, "suspend_type": "S"}, "ts_code,trade_date,suspend_type,suspend_timing"),
            "st": ("stock_st", {"trade_date": compact}, "ts_code,name,trade_date,type,type_name"),
        }
        for key, (api_name, params, fields) in calls.items():
            try:
                result[key] = self.query(api_name, fields=fields, **params)
            except Exception as exc:  # permissions differ by endpoint
                result[key] = []
                result["errors"][key] = str(exc)
        listed: list[dict[str, Any]] = []
        for list_status in ("L", "P", "D"):
            try:
                listed.extend(self.query(
                    "stock_basic", list_status=list_status,
                    fields="ts_code,symbol,name,market,exchange,list_status,list_date,delist_date",
                ))
            except Exception as exc:
                result["errors"][f"stock_basic_{list_status}"] = str(exc)
        result["securities"] = listed
        return result

    def fetch_status_history(self, start_date: str, end_date: str) -> dict[str, Any]:
        params = {"start_date": start_date.replace("-", ""), "end_date": end_date.replace("-", "")}
        result: dict[str, Any] = {"source": self.name, "start_date": start_date, "end_date": end_date, "errors": {}}
        for key, api_name, fields in (
            ("suspension_events", "suspend_d", "ts_code,trade_date,suspend_type,suspend_timing"),
            ("st_daily", "stock_st", "ts_code,name,trade_date,type,type_name"),
        ):
            try:
                result[key] = self.query_all(api_name, fields=fields, **params)
            except Exception as exc:
                result[key] = []
                result["errors"][key] = str(exc)
        return result

    def fetch_interim_financial(self, period: str) -> dict[str, Any]:
        """批量获取指定半年度报告期的三表与财务指标，逐接口保留权限状态。"""
        calls = {
            "income": (
                "income",
                "ts_code,ann_date,f_ann_date,end_date,report_type,basic_eps,total_revenue,revenue,n_income,n_income_attr_p",
            ),
            "balance_sheet": (
                "balancesheet",
                "ts_code,ann_date,f_ann_date,end_date,report_type,total_assets,total_liab,total_hldr_eqy_exc_min_int,money_cap,accounts_receiv,inventories",
            ),
            "cash_flow": (
                "cashflow",
                "ts_code,ann_date,f_ann_date,end_date,report_type,n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,c_cash_equ_end_period",
            ),
            "indicators": (
                "fina_indicator",
                "ts_code,ann_date,end_date,roe,roa,grossprofit_margin,netprofit_margin,netprofit_yoy,or_yoy,assets_yoy,ocfps,debt_to_assets",
            ),
        }
        result: dict[str, Any] = {"source": self.name, "period": period, "datasets": {}, "errors": {}}
        for key, (api_name, fields) in calls.items():
            try:
                result["datasets"][key] = self.query_all(api_name, period=period, fields=fields, page_size=1000)
            except Exception as exc:
                result["datasets"][key] = []
                result["errors"][key] = str(exc)
        return result
