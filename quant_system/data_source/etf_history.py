"""ETF 日线与产品清单（东方财富公开接口），用于防守/反转轨道。"""

from __future__ import annotations

import gzip
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# 产品类型由人工核定，不从名称推断交易方向。
ETF_POOL: dict[str, dict[str, str]] = {
    "511010": {"market": "1", "type": "bond", "label": "国债ETF"},
    "511260": {"market": "1", "type": "bond", "label": "十年国债ETF"},
    "511880": {"market": "1", "type": "money", "label": "银华日利（货币）"},
    "518880": {"market": "1", "type": "gold", "label": "黄金ETF"},
    "510880": {"market": "1", "type": "dividend", "label": "红利ETF"},
    "512890": {"market": "1", "type": "dividend", "label": "红利低波ETF"},
    "510300": {"market": "1", "type": "broad_index", "label": "沪深300ETF"},
    "510500": {"market": "1", "type": "broad_index", "label": "中证500ETF"},
    "159915": {"market": "0", "type": "broad_index", "label": "创业板ETF"},
}
DEFENSIVE_TYPES = ("bond", "gold", "dividend")
INVERSE_NAME_PATTERN = re.compile(r"反向|做空|空头|看空|inverse|杠杆|两倍|2倍|-1", re.IGNORECASE)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = UA
    return session


def fetch_etf_daily(code: str, market: str, session: requests.Session | None = None) -> pd.DataFrame:
    session = session or _session()
    response = session.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": f"{market}.{code}", "klt": 101, "fqt": 1, "beg": "20160101", "end": "20500101",
            "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
        },
        timeout=20,
    )
    response.raise_for_status()
    lines = ((response.json().get("data") or {}).get("klines")) or []
    rows = []
    for line in lines:
        date, open_, close, high, low, volume, amount = line.split(",")[:7]
        rows.append({
            "date": date, "open": float(open_), "close": float(close), "high": float(high),
            "low": float(low), "volume": float(volume), "amount": float(amount),
        })
    return pd.DataFrame(rows)


INVERSE_SCAN_TTL_DAYS = 7


def _clist_page(session: requests.Session, page: int, attempts: int = 4) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={"pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f6",
                        "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024", "fields": "f12,f14"},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # 东方财富对连续请求会断连，退避后重试
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"ETF清单第{page}页获取失败: {last}")


def _sina_etf_names(session: requests.Session) -> list[dict[str, str]]:
    names: list[dict[str, str]] = []
    for page in range(1, 40):
        response = session.get(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
            params={"page": page, "num": 100, "sort": "symbol", "asc": 1, "node": "etf_hq_fund", "_s_r_a": "page"},
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=20,
        )
        response.raise_for_status()
        rows = json.loads(response.text or "[]")
        if not rows:
            break
        names += [{"code": str(row.get("symbol")), "name": str(row.get("name"))} for row in rows]
        time.sleep(0.5)
    return names


def scan_inverse_etfs(session: requests.Session | None = None) -> dict[str, Any]:
    """扫描全部场内 ETF，确认是否存在反向/杠杆产品；东方财富失败时改用新浪清单。"""
    session = session or _session()
    try:
        return {**_scan_eastmoney(session), "source": "eastmoney"}
    except Exception as exc:
        names = _sina_etf_names(session)
        if len(names) < 500:
            raise RuntimeError(f"东方财富失败({str(exc)[-80:]})，新浪清单仅{len(names)}只，不足以下结论")
        matches = [row for row in names if INVERSE_NAME_PATTERN.search(row["name"])]
        return {"etf_count": len(names), "reported_total": None, "inverse_or_leveraged": matches,
                "source": "sina", "primary_error": str(exc)[-120:]}


def _scan_eastmoney(session: requests.Session) -> dict[str, Any]:
    names: list[dict[str, str]] = []
    total = None
    for page in range(1, 40):
        payload = _clist_page(session, page)
        data = payload.get("data") or {}
        total = data.get("total", total)
        diff = data.get("diff") or []
        if not diff:
            break
        names += [{"code": str(row.get("f12")), "name": str(row.get("f14"))} for row in diff]
        if total and len(names) >= int(total):
            break
        time.sleep(1.0)
    if total and len(names) < int(total):
        raise RuntimeError(f"ETF清单不完整: {len(names)}/{total}")
    matches = [row for row in names if INVERSE_NAME_PATTERN.search(row["name"])]
    return {"etf_count": len(names), "reported_total": total, "inverse_or_leveraged": matches}


def cached_inverse_scan(data_dir: Path, *, refresh: bool = True) -> dict[str, Any]:
    """反向ETF清单变化很慢：7天内复用上次完整扫描，失败时保留旧结果并注明。"""
    path = data_dir / "etf_history" / "inverse_scan.json"
    cached: dict[str, Any] = {}
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
    age_days = (time.time() - path.stat().st_mtime) / 86400 if path.exists() else None
    if cached.get("etf_count") and (not refresh or (age_days is not None and age_days < INVERSE_SCAN_TTL_DAYS)):
        return {**cached, "cache": "hit", "age_days": round(age_days or 0, 2)}
    try:
        result = scan_inverse_etfs()
    except Exception as exc:
        if cached.get("etf_count"):
            return {**cached, "cache": "stale_after_error", "error": str(exc)[-200:]}
        return {"error": str(exc)[-200:]}
    result["scanned_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**result, "cache": "refreshed"}


def refresh_etf_history(data_dir: Path) -> dict[str, Any]:
    root = data_dir / "etf_history"
    root.mkdir(parents=True, exist_ok=True)
    session = _session()
    result: dict[str, Any] = {"saved": {}, "errors": {}}
    for code, meta in ETF_POOL.items():
        try:
            frame = fetch_etf_daily(code, meta["market"], session)
            if frame.empty:
                result["errors"][code] = "empty"
                continue
            with gzip.open(root / f"{code}.json.gz", "wt", encoding="utf-8") as stream:
                json.dump(frame.to_dict("records"), stream, ensure_ascii=False)
            result["saved"][code] = {"rows": len(frame), "last": frame["date"].iloc[-1]}
        except Exception as exc:  # 单只失败不影响其他产品
            result["errors"][code] = str(exc)[-120:]
        time.sleep(0.3)
    return result


def load_etf_history(data_dir: Path, code: str) -> pd.DataFrame | None:
    path = data_dir / "etf_history" / f"{code}.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        frame = pd.DataFrame(json.load(stream))
    return frame.sort_values("date").reset_index(drop=True) if not frame.empty else None
