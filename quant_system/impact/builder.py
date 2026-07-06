"""从增强数据中提取对涨跌有实际影响的事件。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from quant_system.config.impact_config import IMPACT_VERSION, NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS
from quant_system.utils.time_utils import now_str


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _keyword_score(text: str) -> int:
    score = 0
    for kw in POSITIVE_KEYWORDS:
        if kw in text:
            score += 8
    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
            score -= 8
    return score


def _earnings_event(enhance: dict[str, Any]) -> dict[str, Any] | None:
    forecast = ((enhance.get("corporate") or {}).get("earnings_forecast") or {})
    if not forecast:
        return None
    change = _to_float(forecast.get("change_pct"), 0.0) or 0.0
    reason = forecast.get("reason") or ""
    score = 0
    if change >= 100:
        score += 35
    elif change >= 30:
        score += 22
    elif change > 0:
        score += 12
    elif change < 0:
        score -= 20
    score += _keyword_score(reason)
    return {
        "event_type": "earnings_forecast",
        "title": f"业绩预告：{forecast.get('forecast_type') or '—'}",
        "period": forecast.get("report_period"),
        "announce_date": forecast.get("announce_date"),
        "impact_score": max(min(score, 60), -60),
        "impact_direction": "positive" if score > 0 else "negative" if score < 0 else "neutral",
        "confidence": "medium",
        "metrics": {
            "change_pct": change,
            "forecast_value": forecast.get("forecast_value"),
            "indicator": forecast.get("indicator"),
        },
        "evidence": [reason] if reason else [],
        "source": forecast.get("source") or "enhance.earnings_forecast",
        "limitations": [] if forecast.get("report_period") == "20260630" else ["not_q2_report_period"],
    }


def _valuation_event(enhance: dict[str, Any]) -> dict[str, Any] | None:
    val = enhance.get("fundamentals") or {}
    pe = _to_float(val.get("pe_ttm"))
    pb = _to_float(val.get("pb"))
    if pe is None and pb is None:
        return None
    score = 0
    evidence = []
    if pe is not None:
        evidence.append(f"PE(TTM)={pe:.2f}")
        if pe > 80:
            score -= 18
        elif pe > 60:
            score -= 12
    if pb is not None:
        evidence.append(f"PB={pb:.2f}")
        if pb > 10:
            score -= 15
        elif pb > 5:
            score -= 8
    if score == 0:
        return None
    return {
        "event_type": "valuation_pressure",
        "title": "估值压力",
        "period": val.get("trade_date"),
        "announce_date": val.get("trade_date"),
        "impact_score": score,
        "impact_direction": "negative",
        "confidence": "medium",
        "metrics": {"pe_ttm": pe, "pb": pb},
        "evidence": evidence,
        "source": val.get("source") or "enhance.fundamentals",
        "limitations": [],
    }


def _lockup_event(enhance: dict[str, Any]) -> dict[str, Any] | None:
    lockups = ((enhance.get("corporate") or {}).get("lockups") or [])
    if not lockups:
        return None

    def unlock_date(row: dict[str, Any]) -> date | None:
        raw = row.get("unlock_date")
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").date()
        except ValueError:
            return None

    today = date.today()
    future_lockups = [
        row for row in lockups
        if (unlock_date(row) is not None and unlock_date(row) >= today)
    ]
    if not future_lockups:
        return None
    first = sorted(future_lockups, key=lambda row: unlock_date(row) or date.max)[0]
    pct_float = _to_float(first.get("pct_float"), 0.0) or 0.0
    value = _to_float(first.get("unlock_value_yi"), 0.0) or 0.0
    score = 0
    if pct_float >= 0.05 or value >= 10:
        score -= 20
    elif pct_float > 0.01 or value >= 1:
        score -= 10
    if score == 0:
        return None
    return {
        "event_type": "lockup_pressure",
        "title": "解禁压力",
        "period": first.get("unlock_date"),
        "announce_date": first.get("unlock_date"),
        "impact_score": score,
        "impact_direction": "negative",
        "confidence": "medium",
        "metrics": {
            "unlock_value_yi": value,
            "pct_float": pct_float,
            "holder_type": first.get("holder_type"),
        },
        "evidence": [f"最近解禁 {first.get('unlock_date')}，规模 {value} 亿元"],
        "source": "enhance.lockups",
        "limitations": [],
    }


def _material_price_event(enhance: dict[str, Any]) -> dict[str, Any] | None:
    forecast = ((enhance.get("corporate") or {}).get("earnings_forecast") or {})
    reason = forecast.get("reason") or ""
    if not any(k in reason for k in ("制冷剂", "价格维持高位", "氟化工", "锂电")):
        return None
    score = 18
    if "价格维持高位" in reason:
        score += 12
    if "市场复苏" in reason:
        score += 8
    return {
        "event_type": "material_or_product_price",
        "title": "生产相关产品/材料价格影响",
        "period": forecast.get("report_period"),
        "announce_date": forecast.get("announce_date"),
        "impact_score": score,
        "impact_direction": "positive",
        "confidence": "medium",
        "metrics": {
            "forecast_change_pct": _to_float(forecast.get("change_pct")),
            "forecast_value": forecast.get("forecast_value"),
        },
        "evidence": [reason],
        "source": "enhance.earnings_forecast.reason",
        "limitations": ["uses_company_reason_text"],
    }


def _requested_q2_gap(code: str, enhance: dict[str, Any]) -> dict[str, Any] | None:
    if code != "603629":
        return None
    forecast = ((enhance.get("corporate") or {}).get("earnings_forecast") or {})
    if forecast.get("report_period") == "20260630":
        return None
    return {
        "event_type": "q2_profit_growth_gap",
        "title": "二季度利润增长数据待补充",
        "period": "20260630",
        "announce_date": None,
        "impact_score": 0,
        "impact_direction": "neutral",
        "confidence": "low",
        "metrics": {},
        "evidence": ["当前增强数据未采集到 2026Q2 正式利润增长或半年度业绩预告。"],
        "source": "system_gap",
        "limitations": ["requires_q2_official_report_or_forecast"],
    }


def build_impact_payload(code: str, name: str, enhance: dict[str, Any] | None) -> dict[str, Any]:
    enhance = enhance or {}
    events = [
        e for e in (
            _earnings_event(enhance),
            _valuation_event(enhance),
            _lockup_event(enhance),
            _material_price_event(enhance),
            _requested_q2_gap(code, enhance),
        )
        if e
    ]
    total = sum(int(e.get("impact_score") or 0) for e in events)
    if total > 15:
        direction = "positive"
    elif total < -15:
        direction = "negative"
    else:
        direction = "neutral"
    return {
        "code": code,
        "name": name,
        "trade_date": enhance.get("trade_date"),
        "version": IMPACT_VERSION,
        "impact_score": max(min(total, 100), -100),
        "impact_direction": direction,
        "events": events,
        "limitations": sorted({x for e in events for x in (e.get("limitations") or [])}),
        "updated_at": now_str(),
    }
