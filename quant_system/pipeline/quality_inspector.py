"""数据质量巡检。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.factor_config import (
    CROSS_SOURCE_WARN_PCT,
    FACTOR_MIN_SCORE,
    QUALITY_OK,
    QUALITY_WARN,
)
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import TradeCalendar, get_calendar


def kline_dates(df: pd.DataFrame) -> set[str]:
    if df is None or df.empty or "date" not in df.columns:
        return set()
    return {pd.to_datetime(r["date"]).strftime("%Y-%m-%d") for _, r in df.iterrows()}


def find_missing_trade_dates(
    df: pd.DataFrame,
    start: str,
    end: str,
    calendar: TradeCalendar | None = None,
) -> list[str]:
    """找出 [start, end] 区间内 K 线缺失的交易日。"""
    cal = calendar or get_calendar()
    expected = set(cal.trade_days_between(start, end))
    actual = kline_dates(df)
    return sorted(expected - actual)


def _calc_quality_score(
    *,
    recent_missing: list[str],
    window_trade_days: int,
    lag_trade_days: int,
    dup_dates: int,
    zero_vol_ratio: float,
    cross_source_diff: float | None = None,
    cross_max_diff_pct: float | None = None,
) -> float:
    score = 100.0
    score -= min(30.0, len(recent_missing) * 5.0)
    score -= min(20.0, lag_trade_days * 5.0)
    score -= min(15.0, dup_dates * 5.0)
    if zero_vol_ratio > 0.3:
        score -= 10.0
    if window_trade_days > 0:
        missing_rate = len(recent_missing) / window_trade_days
        if missing_rate > 0.1:
            score -= 10.0
    if cross_max_diff_pct is not None and cross_max_diff_pct > CROSS_SOURCE_WARN_PCT:
        score -= min(15.0, (cross_max_diff_pct - CROSS_SOURCE_WARN_PCT) * 2)
    elif cross_source_diff is not None and cross_source_diff * 100 > CROSS_SOURCE_WARN_PCT:
        score -= 8.0
    return max(0.0, min(100.0, round(score, 1)))


def _status_from_score(score: float) -> str:
    if score >= QUALITY_OK:
        return "ok"
    if score >= QUALITY_WARN:
        return "warning"
    return "error"


def is_factor_eligible(quality: dict[str, Any]) -> bool:
    return quality.get("quality_score", 0) >= FACTOR_MIN_SCORE and quality.get("status") != "error"


def inspect_kline_df(
    code: str,
    df: pd.DataFrame,
    calendar: TradeCalendar | None = None,
    lookback_days: int = 60,
    cross_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """巡检单只股票 K 线质量，输出 Quantification.md §2.3 结构。"""
    cal = calendar or get_calendar()
    checked_at = now_str()
    issues: list[str] = []

    if df is None or df.empty:
        return {
            "code": code,
            "trade_date": cal.latest_trade_day(),
            "status": "error",
            "quality_score": 0,
            "missing_rate": 1.0,
            "duplicate_count": 0,
            "cross_source_diff": None,
            "rows": 0,
            "issues": ["K 线为空"],
            "missing_dates": [],
            "factor_eligible": False,
            "checked_at": checked_at,
        }

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    start = df["date"].iloc[0].strftime("%Y-%m-%d")
    end = df["date"].iloc[-1].strftime("%Y-%m-%d")
    latest_expected = cal.latest_trade_day()
    missing = find_missing_trade_dates(df, start, end, cal)

    window_start = (df["date"].iloc[-1] - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    recent_missing = [d for d in missing if d >= window_start]
    window_trade_days = len(cal.trade_days_between(window_start, end))

    if recent_missing:
        issues.append(f"近 {lookback_days} 日缺失 {len(recent_missing)} 个交易日")

    last_date = end
    lag_trade_days = 0
    if last_date < latest_expected:
        lag_days_list = [d for d in cal.trade_days_between(last_date, latest_expected) if d > last_date]
        lag_trade_days = len(lag_days_list)
        issues.append(f"K 线末日期 {last_date} 落后于最近交易日 {latest_expected}")

    zero_vol = int((df["volume"].fillna(0) == 0).sum()) if "volume" in df.columns else 0
    zero_vol_ratio = zero_vol / len(df) if len(df) else 0.0
    if zero_vol_ratio > 0.3:
        issues.append(f"零成交量占比过高: {zero_vol}/{len(df)}")

    dup_dates = int(df["date"].duplicated().sum())
    if dup_dates:
        issues.append(f"存在重复日期: {dup_dates} 条")

    cross_diff = None
    cross_detail = cross_source or {}
    if cross_detail.get("compared_days", 0) > 0:
        cross_diff = cross_detail.get("cross_source_diff")
        max_pct = cross_detail.get("max_diff_pct")
        alt = cross_detail.get("alt_source", "alt")
        if max_pct is not None and max_pct > CROSS_SOURCE_WARN_PCT:
            issues.append(
                f"跨源偏差超阈值: vs {alt} 最大 {max_pct:.2f}%（阈值 {CROSS_SOURCE_WARN_PCT}%）"
            )
        elif cross_diff is not None:
            issues.append(
                f"跨源校验 vs {alt}: 近 {cross_detail['compared_days']} 日"
                f" 均偏 {cross_diff * 100:.3f}%"
            )

    missing_rate = round(len(recent_missing) / window_trade_days, 4) if window_trade_days else 0.0
    quality_score = _calc_quality_score(
        recent_missing=recent_missing,
        window_trade_days=window_trade_days,
        lag_trade_days=lag_trade_days,
        dup_dates=dup_dates,
        zero_vol_ratio=zero_vol_ratio,
        cross_source_diff=cross_diff,
        cross_max_diff_pct=cross_detail.get("max_diff_pct"),
    )
    status = _status_from_score(quality_score)

    return {
        "code": code,
        "trade_date": latest_expected,
        "status": status,
        "quality_score": quality_score,
        "missing_rate": missing_rate,
        "duplicate_count": dup_dates,
        "cross_source_diff": cross_diff,
        "cross_source": cross_detail if cross_detail else None,
        "rows": len(df),
        "date_range": [start, end],
        "latest_expected": latest_expected,
        "missing_dates": recent_missing,
        "issues": issues,
        "factor_eligible": is_factor_eligible({
            "quality_score": quality_score,
            "status": status,
        }),
        "checked_at": checked_at,
    }


def build_inspect_report(results: list[dict[str, Any]], updated_at: str) -> dict[str, Any]:
    summary = {"ok": 0, "warning": 0, "error": 0, "factor_blocked": 0}
    for r in results:
        summary[r.get("status", "error")] = summary.get(r.get("status", "error"), 0) + 1
        if not r.get("factor_eligible", False):
            summary["factor_blocked"] += 1
    return {
        "updated_at": updated_at,
        "total": len(results),
        "summary": summary,
        "stocks": results,
    }
