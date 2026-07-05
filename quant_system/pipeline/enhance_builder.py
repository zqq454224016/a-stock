"""P1-3 数据增强 payload 组装。"""

from __future__ import annotations

from typing import Any

from quant_system.config.enhance_config import (
    DIVIDEND_LIMIT,
    ENHANCE_VERSION,
    LOCKUP_LIMIT,
    NORTHBOUND_DAYS,
)
from quant_system.utils.time_utils import now_str, today_str


def _index_context(market: dict[str, Any] | None, stock_analysis: dict[str, Any] | None) -> dict[str, Any]:
    market = market or {}
    analysis = (stock_analysis or {}).get("analysis") or {}
    returns = analysis.get("returns") or {}
    indices = market.get("indices") or []
    benchmarks = [
        {
            "name": i.get("name"),
            "code": i.get("code"),
            "close": i.get("close"),
            "change_pct": i.get("change_pct"),
        }
        for i in indices
    ]
    return {
        "trade_date": market.get("trade_date"),
        "benchmarks": benchmarks,
        "market_fund_flow": market.get("fund_flow") or {},
        "stock_return_20d": returns.get("d20"),
    }


def _cross_source_from_quality(quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quality:
        return None
    diff = quality.get("cross_source_diff")
    if not diff:
        return None
    return {
        "status": diff.get("status"),
        "primary_source": diff.get("primary_source"),
        "compare_source": diff.get("compare_source"),
        "close_diff_pct": diff.get("close_diff_pct"),
        "checked_at": diff.get("checked_at"),
    }


def build_enhance_payload(
    code: str,
    name: str,
    *,
    valuation: dict[str, Any],
    dividends: list[dict[str, Any]],
    lockups: list[dict[str, Any]],
    forecast: dict[str, Any] | None,
    northbound: dict[str, Any],
    margin: dict[str, Any] | None,
    market: dict[str, Any] | None,
    stock_analysis: dict[str, Any] | None,
    quality: dict[str, Any] | None,
    sources_failed: list[str],
) -> dict[str, Any]:
    trade_date = (
        valuation.get("trade_date")
        or northbound.get("trade_date")
        or (market or {}).get("trade_date")
        or today_str()
    )
    limitations: list[str] = []
    if sources_failed:
        limitations.append("partial_source_failure")
    if not valuation.get("source"):
        limitations.append("valuation_missing")
    if not northbound:
        limitations.append("northbound_missing")
    if not dividends:
        limitations.append("dividend_missing")

    return {
        "code": code,
        "name": name,
        "trade_date": trade_date,
        "updated_at": now_str(),
        "version": ENHANCE_VERSION,
        "fundamentals": valuation,
        "corporate": {
            "dividends": dividends[:DIVIDEND_LIMIT],
            "lockups": lockups[:LOCKUP_LIMIT],
            "earnings_forecast": forecast,
        },
        "fund_flow": {
            "northbound": northbound,
            "margin": margin,
        },
        "index_context": _index_context(market, stock_analysis),
        "cross_source": _cross_source_from_quality(quality),
        "quality_ref": {
            "status": (quality or {}).get("status"),
            "quality_score": (quality or {}).get("quality_score"),
        },
        "limitations": limitations,
        "sources_failed": sorted(set(sources_failed)),
    }


def summarize_enhance(payload: dict[str, Any]) -> dict[str, Any]:
    """索引页摘要。"""
    val = payload.get("fundamentals") or {}
    nb = (payload.get("fund_flow") or {}).get("northbound") or {}
    corp = payload.get("corporate") or {}

    def _r(v: Any, n: int = 2) -> Any:
        if v is None:
            return None
        try:
            return round(float(v), n)
        except (TypeError, ValueError):
            return v

    return {
        "code": payload.get("code"),
        "name": payload.get("name"),
        "trade_date": payload.get("trade_date"),
        "pe_ttm": _r(val.get("pe_ttm")),
        "pb": _r(val.get("pb")),
        "market_cap_yi": _r(val.get("market_cap_yi")),
        "north_hold_pct": _r(nb.get("hold_pct")),
        "north_net_buy_yi": _r(nb.get("net_buy_amount_yi"), 4),
        "dividend_count": len(corp.get("dividends") or []),
        "next_lockup": (corp.get("lockups") or [{}])[0].get("unlock_date") if corp.get("lockups") else None,
        "limitations": payload.get("limitations") or [],
    }
