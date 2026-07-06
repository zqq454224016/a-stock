"""基本面与资金因子（P1-3 增强数据）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from quant_system.config.enhance_config import ENHANCE_VERSION
from quant_system.utils.time_utils import today_str


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, round(score, 1)))


def _valuation_score(pe: float | None, pb: float | None) -> float:
    score = 50.0
    if pe is not None:
        if pe < 0:
            score -= 15
        elif pe < 15:
            score += 10
        elif pe < 30:
            score += 5
        elif pe > 60:
            score -= 8
        elif pe > 100:
            score -= 15
    if pb is not None:
        if pb < 1.5:
            score += 6
        elif pb < 3:
            score += 2
        elif pb > 6:
            score -= 6
        elif pb > 10:
            score -= 10
    return score


def _lockup_penalty(lockups: list[dict[str, Any]], ref_date: str) -> float:
    if not lockups:
        return 0.0
    try:
        ref = datetime.strptime(ref_date[:10], "%Y-%m-%d")
    except ValueError:
        ref = datetime.now()
    penalty = 0.0
    for item in lockups[:2]:
        unlock = item.get("unlock_date")
        if not unlock:
            continue
        try:
            dt = datetime.strptime(str(unlock)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        days = (dt - ref).days
        if days < 0:
            continue
        pct = float(item.get("pct_float") or item.get("pct_total") or 0)
        if days <= 30 and pct >= 0.05:
            penalty += 12
        elif days <= 90 and pct >= 0.03:
            penalty += 6
    return penalty


def _forecast_bonus(forecast: dict[str, Any] | None) -> float:
    if not forecast:
        return 0.0
    change = forecast.get("change_pct")
    if change is None:
        return 0.0
    change = float(change)
    ftype = str(forecast.get("forecast_type", ""))
    if "预减" in ftype or "亏损" in ftype or change < -20:
        return -10
    if change >= 50:
        return 8
    if change >= 20:
        return 5
    if change >= 0:
        return 2
    return -5


def score_fundamental(enhance: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if not enhance:
        return None, {}
    val = enhance.get("fundamentals") or {}
    corp = enhance.get("corporate") or {}
    if not val.get("source"):
        return None, {}

    pe = val.get("pe_ttm")
    pb = val.get("pb")
    score = _valuation_score(
        float(pe) if pe is not None else None,
        float(pb) if pb is not None else None,
    )
    score -= _lockup_penalty(corp.get("lockups") or [], enhance.get("trade_date") or today_str())
    score += _forecast_bonus(corp.get("earnings_forecast"))

    details = {
        "pe_ttm": pe,
        "pb": pb,
        "market_cap_yi": val.get("market_cap_yi"),
        "valuation_source": val.get("source"),
        "next_lockup": (corp.get("lockups") or [{}])[0].get("unlock_date") if corp.get("lockups") else None,
        "forecast_type": (corp.get("earnings_forecast") or {}).get("forecast_type"),
    }
    return _clamp(score), details


def score_fund_flow(enhance: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    if not enhance:
        return None, {}
    ff = enhance.get("fund_flow") or {}
    nb = ff.get("northbound") or {}
    margin = ff.get("margin") or {}
    has_nb = bool(nb.get("trade_date") or nb.get("hold_pct") is not None)
    has_margin = bool(margin.get("margin_balance_yi") is not None)
    if not has_nb and not has_margin:
        return None, {}

    score = 50.0
    if nb.get("hold_pct") is not None:
        score += min(float(nb["hold_pct"]) * 1.5, 12)
    if nb.get("net_buy_amount_yi") is not None:
        net = float(nb["net_buy_amount_yi"])
        score += max(-10, min(10, net * 25))
    if margin.get("margin_buy_yi") is not None and margin.get("margin_balance_yi") is not None:
        buy = float(margin["margin_buy_yi"])
        bal = float(margin["margin_balance_yi"])
        if bal > 0:
            ratio = buy / bal
            if ratio >= 0.15:
                score += 5
            elif ratio <= 0.05:
                score -= 3

    details = {
        "north_hold_pct": nb.get("hold_pct"),
        "north_net_buy_yi": nb.get("net_buy_amount_yi"),
        "margin_balance_yi": margin.get("margin_balance_yi"),
        "has_northbound": has_nb,
        "has_margin": has_margin,
    }
    return _clamp(score), details


def compute_enhance_factors(enhance: dict[str, Any] | None) -> dict[str, Any]:
    """从 P1-3 增强 JSON 计算基本面/资金因子。"""
    fund_score, fund_detail = score_fundamental(enhance)
    flow_score, flow_detail = score_fund_flow(enhance)
    limitations: list[str] = []
    if fund_score is None:
        limitations.append("fundamental_missing")
    if flow_score is None:
        limitations.append("fund_flow_missing")

    return {
        "enhance_version": ENHANCE_VERSION,
        "fundamental_score": fund_score,
        "fund_flow_score": flow_score,
        "fundamental_detail": fund_detail,
        "fund_flow_detail": flow_detail,
        "limitations": limitations,
    }
