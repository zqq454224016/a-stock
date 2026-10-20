"""Deterministic point-in-time quality gate for the long-term strategy."""
from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED = ("revenue_growth", "profit_growth", "operating_cash_flow", "debt_to_assets")

def quality_gate(facts: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED if facts.get(key) is None]
    if missing:
        return {"passed": False, "score": None, "missing": missing, "reason": "point_in_time_fields_missing"}
    checks = {
        "revenue_growth": float(facts["revenue_growth"]) > 0,
        "profit_growth": float(facts["profit_growth"]) > 0,
        "operating_cash_flow": float(facts["operating_cash_flow"]) > 0,
        "debt_to_assets": float(facts["debt_to_assets"]) < 0.75,
    }
    return {"passed": all(checks.values()), "score": round(sum(checks.values()) / 4 * 100, 2), "missing": [], "checks": checks}

def exit_on_quality_break(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev, now = quality_gate(previous), quality_gate(current)
    if now["missing"]:
        return {"exit": False, "reason": "await_verified_point_in_time_data"}
    deteriorated = (float(current["revenue_growth"]) < float(previous.get("revenue_growth", 0))
                    and float(current["profit_growth"]) < float(previous.get("profit_growth", 0))
                    and float(current["operating_cash_flow"]) < 0)
    return {"exit": bool(prev.get("passed") and deteriorated), "reason": "confirmed_quality_break" if deteriorated else "no_confirmed_break"}


# v2（2026-10-20 预登记）：公开季报摘要没有资产负债率，以当期 ROE>0 代替负债约束。
REQUIRED_V2 = ("revenue_yoy_pct", "net_profit_yoy_pct", "operating_cashflow_per_share", "roe_pct")
QUALITY_GATE_VERSION = "long_term_quality_v2_public_summary"


def quality_gate_v2(metrics: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_V2 if metrics.get(key) is None]
    if missing:
        return {"passed": False, "known": False, "missing": missing}
    checks = {key: float(metrics[key]) > 0 for key in REQUIRED_V2}
    return {"passed": all(checks.values()), "known": True, "missing": [], "checks": checks}


def statutory_deadline(report_period: str) -> date:
    """法定最晚披露日：一季报4/30、半年报8/31、三季报10/31、年报次年4/30。"""
    year, month = int(report_period[:4]), int(report_period[5:7])
    if month == 3:
        return date(year, 4, 30)
    if month == 6:
        return date(year, 8, 31)
    if month == 9:
        return date(year, 10, 31)
    return date(year + 1, 4, 30)


def known_date(record: dict[str, Any]) -> date | None:
    """数据源对旧报告期返回的是最近一次披露日（常晚一年）；取它与法定截止日中较早者。"""
    period = str(record.get("report_period") or "")
    if len(period) < 10:
        return None
    deadline = statutory_deadline(period)
    raw = str(record.get("known_at") or record.get("published_at") or "")[:10]
    try:
        published = date.fromisoformat(raw)
    except ValueError:
        return deadline
    return min(published, deadline)


def load_quality_timeline(data_dir: Path, code: str) -> pd.DataFrame:
    """按“可知日”排列的质量门时间线；同一日取最新报告期。"""
    path = data_dir / "point_in_time_financials" / "by_code" / f"{code}.json.gz"
    if not path.exists():
        return pd.DataFrame(columns=["known_date", "report_period", "pass", "known"])
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            records = json.load(stream)
    except (OSError, ValueError):
        return pd.DataFrame(columns=["known_date", "report_period", "pass", "known"])
    rows = []
    for record in records:
        when = known_date(record)
        if when is None:
            continue
        gate = quality_gate_v2(record.get("metrics") or {})
        rows.append({"known_date": pd.Timestamp(when), "report_period": record["report_period"],
                     "pass": gate["passed"], "known": gate["known"]})
    if not rows:
        return pd.DataFrame(columns=["known_date", "report_period", "pass", "known"])
    frame = pd.DataFrame(rows).sort_values(["known_date", "report_period"])
    return frame.drop_duplicates("known_date", keep="last").reset_index(drop=True)


def attach_point_in_time_quality(work: pd.DataFrame, data_dir: Path, code: str) -> pd.DataFrame:
    """把每个交易日当时可知的最新报告质量门接到日线上（as-of 连接，只看过去）。"""
    timeline = load_quality_timeline(data_dir, code)
    out = work.copy()
    if timeline.empty:
        out["fundamental_quality_known"] = False
        out["fundamental_quality_pass"] = False
        return out
    date_column = "date" if "date" in out.columns else "trade_date"
    dates = pd.to_datetime(out[date_column].astype(str).str[:10], errors="coerce").astype("datetime64[ns]")
    left = pd.DataFrame({"_row": range(len(out)), "_date": dates}).dropna().sort_values("_date")
    timeline = timeline.assign(known_date=timeline["known_date"].astype("datetime64[ns]"))
    merged = pd.merge_asof(left, timeline, left_on="_date", right_on="known_date", direction="backward")
    merged = merged.set_index("_row").reindex(range(len(out)))
    # 超过一年没有新报告视为未知，避免用陈旧财报
    stale = (merged["_date"] - merged["known_date"]).dt.days > 400
    out["fundamental_quality_known"] = (merged["known"].fillna(False).astype(bool) & ~stale.fillna(True)).to_numpy()
    out["fundamental_quality_pass"] = (merged["pass"].fillna(False).astype(bool)
                                       & out["fundamental_quality_known"]).to_numpy()
    return out
