"""Low-cost public HTTP sources adapted from simonlin1212/a-stock-data.

Only deterministic transport and parsing live here. AI is not involved in
normalization, feature calculation or scoring.
"""

from __future__ import annotations

import random
import json
import re
import threading
import time
from datetime import date
from typing import Any, Iterable

import requests

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import normalize_code

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
_SH_INDICES = {"000010", "000016", "000300", "000688", "000852", "000905"}


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value) / scale
    except (TypeError, ValueError):
        return None


def tencent_prefix(value: str) -> str:
    text = str(value).strip().lower()
    if text.startswith(("sh", "sz", "bj")):
        return text
    code = normalize_code(text)
    if code.startswith("92"):
        return f"bj{code}"
    if code in _SH_INDICES or code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def parse_tencent_quotes(text: str, requested: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Parse qt.gtimg.cn's GBK payload without using ambiguous bare-code keys."""
    requested = requested or {}
    rows: list[dict[str, Any]] = []
    for line in text.split(";"):
        if "=" not in line or '"' not in line:
            continue
        query_key = line.split("=", 1)[0].rsplit("_", 1)[-1].lower()
        values = line.split('"', 2)[1].split("~")
        if len(values) < 53:
            continue
        raw_code = requested.get(query_key, values[2] or query_key[2:])
        code = normalize_code(raw_code)
        price = _number(values[3])
        if not code or not price:
            continue
        rows.append({
            "code": code,
            "symbol": f"{code}.SH" if query_key.startswith("sh") else f"{code}.BJ" if query_key.startswith("bj") else f"{code}.SZ",
            "name": values[1],
            "price": price,
            "previous_close": _number(values[4]),
            "open": _number(values[5]),
            "volume_lot": _number(values[6]),
            "change": _number(values[31]),
            "change_pct": _number(values[32]),
            "high": _number(values[33]),
            "low": _number(values[34]),
            "amount_yi": _number(values[37], scale=10000.0),
            "turnover_pct": _number(values[38]),
            "pe_ttm": _number(values[39]),
            "amplitude_pct": _number(values[43]),
            "total_market_cap_yi": _number(values[45]),
            "float_market_cap_yi": _number(values[44]),
            "pb": _number(values[46]),
            "limit_up": _number(values[47]),
            "limit_down": _number(values[48]),
            "quote_time": values[30] if len(values) > 30 else None,
            "source": "tencent",
        })
    return rows


class PublicHttpAPI:
    source_name = "public_http"

    def __init__(self, config: CrawlerConfig | None = None, session: requests.Session | None = None):
        self.config = config or CrawlerConfig()
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self._em_lock = threading.Lock()
        self._em_last_call = 0.0

    def fetch_tencent_quotes(self, codes: Iterable[str]) -> list[dict[str, Any]]:
        prefixed = [tencent_prefix(code) for code in codes]
        if not prefixed:
            return []
        result: list[dict[str, Any]] = []
        size = max(1, self.config.tencent_quote_batch_size)
        for start in range(0, len(prefixed), size):
            batch = prefixed[start:start + size]
            mapping = {item: item[2:] for item in batch}
            response = self.session.get(
                "https://qt.gtimg.cn/q=" + ",".join(batch),
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            response.encoding = "gbk"
            result.extend(parse_tencent_quotes(response.text, mapping))
        return result

    def fetch_tencent_minutes(self, code: str) -> list[dict[str, Any]]:
        """Fetch today's one-minute series and convert cumulative volume/amount to increments."""
        symbol = tencent_prefix(code)
        response = self.session.get(
            f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}",
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        node = (((response.json().get("data") or {}).get(symbol) or {}).get("data") or {})
        day = str(node.get("date") or "")
        result, previous_volume, previous_amount = [], 0.0, 0.0
        for raw in node.get("data") or []:
            parts = str(raw).split()
            if len(parts) < 4:
                continue
            minute, price, cumulative_volume, cumulative_amount = parts[:4]
            volume, amount = float(cumulative_volume), float(cumulative_amount)
            result.append({
                "date": f"{day[:4]}-{day[4:6]}-{day[6:8]} {minute[:2]}:{minute[2:]}",
                "open": float(price), "high": float(price), "low": float(price), "close": float(price),
                "volume": max(0.0, volume - previous_volume),
                "amount": max(0.0, amount - previous_amount), "source": "tencent_minute",
            })
            previous_volume, previous_amount = volume, amount
        return result

    def _eastmoney_get(self, endpoint: str, params: dict[str, Any]) -> requests.Response:
        with self._em_lock:
            wait = self.config.eastmoney_min_interval_sec - (time.monotonic() - self._em_last_call)
            if wait > 0:
                time.sleep(wait + random.uniform(0.05, 0.25))
            try:
                response = self.session.get(
                    f"https://push2ex.eastmoney.com/{endpoint}",
                    params=params,
                    headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": UA},
                    timeout=self.config.request_timeout,
                )
                response.raise_for_status()
                return response
            finally:
                self._em_last_call = time.monotonic()

    def _eastmoney_datacenter(
        self, report_name: str, *, filter_text: str, page_size: int,
        sort_columns: str, sort_types: str = "-1",
    ) -> list[dict[str, Any]]:
        with self._em_lock:
            wait = self.config.eastmoney_min_interval_sec - (time.monotonic() - self._em_last_call)
            if wait > 0:
                time.sleep(wait + random.uniform(0.05, 0.25))
            try:
                response = self.session.get(
                    "https://datacenter-web.eastmoney.com/api/data/v1/get",
                    params={
                        "reportName": report_name, "columns": "ALL", "filter": filter_text,
                        "pageNumber": "1", "pageSize": str(page_size),
                        "sortColumns": sort_columns, "sortTypes": sort_types,
                        "source": "WEB", "client": "WEB",
                    },
                    timeout=self.config.request_timeout,
                )
                response.raise_for_status()
                return (response.json().get("result") or {}).get("data") or []
            finally:
                self._em_last_call = time.monotonic()

    def fetch_limit_pool(self, pool: str, trade_date: str | None = None) -> list[dict[str, Any]]:
        endpoints = {
            "limit_up": ("getTopicZTPool", "fbt:asc"),
            "broken": ("getTopicZBPool", "fbt:asc"),
            "limit_down": ("getTopicDTPool", "fund:asc"),
            "yesterday_limit_up": ("getYesterdayZTPool", "zdp:desc"),
        }
        endpoint, sort = endpoints[pool]
        day = (trade_date or date.today().isoformat()).replace("-", "")
        response = self._eastmoney_get(endpoint, {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 10000,
            "sort": sort, "date": day,
        })
        raw = (response.json().get("data") or {}).get("pool") or []
        return [self._normalize_limit_pool_row(pool, row) for row in raw]

    @staticmethod
    def _normalize_limit_pool_row(pool: str, row: dict[str, Any]) -> dict[str, Any]:
        stat = row.get("zttj") or {}
        return {
            "pool": pool,
            "code": normalize_code(row.get("c")),
            "name": row.get("n"),
            "price": _number(row.get("p"), scale=1000.0),
            "change_pct": _number(row.get("zdp")),
            "turnover_pct": _number(row.get("hs")),
            "amount": _number(row.get("amount")),
            "float_market_cap": _number(row.get("ltsz")),
            "seal_fund": _number(row.get("fund")),
            "first_seal": row.get("fbt"),
            "last_seal": row.get("lbt"),
            "break_times": row.get("zbc"),
            "consecutive_limit_days": row.get("lbc") or row.get("days"),
            "stat_days": stat.get("days"),
            "stat_limit_count": stat.get("ct"),
            "industry": row.get("hybk") or "",
            "source": "eastmoney_push2ex",
        }

    def fetch_sina_financial_report(
        self, code: str, report_type: str = "lrb", periods: int = 8,
    ) -> list[dict[str, Any]]:
        if report_type not in {"fzb", "lrb", "llb"}:
            raise ValueError(f"unsupported report_type: {report_type}")
        normalized = normalize_code(code)
        prefix = "sh" if normalized.startswith(("5", "6", "9")) else "sz"
        response = self.session.get(
            "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
            params={"paperCode": f"{prefix}{normalized}", "source": report_type, "type": "0", "page": "1", "num": periods},
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        report_list = response.json().get("result", {}).get("data", {}).get("report_list", {}) or {}
        rows: list[dict[str, Any]] = []
        for period in sorted(report_list, reverse=True)[:periods]:
            record: dict[str, Any] = {"period_end": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
            for item in report_list[period].get("data", []) or []:
                title = str(item.get("item_title") or "").strip()
                if not title or item.get("item_value") is None:
                    continue
                record[title] = item.get("item_value")
                if item.get("item_tongbi") not in (None, ""):
                    record[f"{title}_同比"] = item.get("item_tongbi")
            rows.append(record)
        return rows

    def fetch_margin_trading(self, code: str, page_size: int = 30) -> list[dict[str, Any]]:
        code = normalize_code(code)
        rows = self._eastmoney_datacenter(
            "RPTA_WEB_RZRQ_GGMX", filter_text=f'(SCODE="{code}")',
            page_size=page_size, sort_columns="DATE",
        )
        return [{
            "date": str(row.get("DATE") or "")[:10],
            "financing_balance": _number(row.get("RZYE")),
            "financing_buy": _number(row.get("RZMRE")),
            "financing_repay": _number(row.get("RZCHE")),
            "securities_lending_balance": _number(row.get("RQYE")),
            "securities_lending_sell_volume": _number(row.get("RQMCL")),
            "securities_lending_repay_volume": _number(row.get("RQCHL")),
            "margin_balance": _number(row.get("RZRQYE")),
        } for row in rows]

    def fetch_block_trades(self, code: str, page_size: int = 20) -> list[dict[str, Any]]:
        code = normalize_code(code)
        rows = self._eastmoney_datacenter(
            "RPT_DATA_BLOCKTRADE", filter_text=f'(SECURITY_CODE="{code}")',
            page_size=page_size, sort_columns="TRADE_DATE",
        )
        result = []
        for row in rows:
            close = _number(row.get("CLOSE_PRICE")) or 0.0
            price = _number(row.get("DEAL_PRICE")) or 0.0
            result.append({
                "date": str(row.get("TRADE_DATE") or "")[:10],
                "price": price, "close": close,
                "premium_pct": round((price / close - 1) * 100, 4) if close else None,
                "volume": _number(row.get("DEAL_VOLUME")),
                "amount": _number(row.get("DEAL_AMT")),
                "buyer": row.get("BUYER_NAME") or "",
                "seller": row.get("SELLER_NAME") or "",
            })
        return result

    def fetch_lockup_expiry(
        self, code: str, trade_date: str, forward_days: int = 90,
    ) -> dict[str, list[dict[str, Any]]]:
        from datetime import datetime, timedelta

        code = normalize_code(code)
        common = dict(report_name="RPT_LIFT_STAGE", page_size=20, sort_columns="FREE_DATE")
        history_raw = self._eastmoney_datacenter(
            filter_text=f'(SECURITY_CODE="{code}")', **common,
        )
        end_date = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
        upcoming_raw = self._eastmoney_datacenter(
            filter_text=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end_date}\')',
            sort_types="1", **common,
        )

        def normalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{
                "date": str(row.get("FREE_DATE") or "")[:10],
                "type": row.get("FREE_SHARES_TYPE") or "",
                "shares_wan": _number(row.get("FREE_SHARES")),
                "tradable_shares_wan": _number(row.get("ABLE_FREE_SHARES")),
                "total_share_ratio": _number(row.get("FREE_RATIO")),
            } for row in rows]

        return {"history": normalize(history_raw), "upcoming": normalize(upcoming_raw)}

    def fetch_official_dragon_tiger(self, trade_date: str) -> dict[str, Any]:
        """Daily official SSE/SZSE backup. SSE text is retained as source evidence."""
        result: dict[str, Any] = {"trade_date": trade_date, "szse": [], "sse_raw": "", "errors": {}}
        try:
            response = self.session.get(
                "https://www.szse.cn/api/report/ShowReport/data",
                params={
                    "SHOWTYPE": "JSON", "CATALOGID": "1842_xxpl", "TABKEY": "tab1",
                    "txtStart": trade_date, "txtEnd": trade_date, "random": "0.9",
                },
                headers={"Referer": "https://www.szse.cn/disclosure/supervision/dealinfo/index.html", "User-Agent": UA},
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            tables = response.json()
            data = tables[0].get("data", []) if tables else []
            result["szse"] = [{
                "code": normalize_code(row.get("zqdm")), "name": row.get("zqjc"),
                "amount": _number(row.get("cjje")), "reason": row.get("plyy") or "",
            } for row in data]
        except Exception as exc:
            result["errors"]["szse"] = str(exc)
        try:
            response = self.session.get(
                "https://query.sse.com.cn/infodisplay/showTradePublicFile.do",
                params={"jsonCallBack": "cb", "isPagination": "false", "dateTx": trade_date},
                headers={"Referer": "https://www.sse.com.cn/disclosure/diclosure/public/", "User-Agent": UA},
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            match = re.search(r"^[^(]*\((.*)\)\s*$", response.text, re.S)
            payload = json.loads(match.group(1)) if match else {}
            result["sse_raw"] = "\n".join(payload.get("fileContents") or [])
        except Exception as exc:
            result["errors"]["sse"] = str(exc)
        return result
