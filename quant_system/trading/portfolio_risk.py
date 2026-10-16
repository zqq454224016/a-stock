"""Portfolio risk checks for recommendation paper accounts (no broker)."""

from __future__ import annotations

from typing import Any

PORTFOLIO_RISK_ENGINE_VERSION = "1.0.0"

DEFAULT_LIMITS = {
    "max_single_weight": 0.25,
    "max_invested_weight": 0.80,
    "min_cash_weight": 0.10,
    "max_industry_weight": 0.45,
    "account_drawdown_pct": -0.10,
    "position_loss_pct": -8.0,
}


def capabilities() -> dict[str, Any]:
    return {
        "version": PORTFOLIO_RISK_ENGINE_VERSION,
        "scope": "paper_recommendation_only",
        "broker_integration": False,
        "supports": [
            "single_position_cap",
            "gross_exposure_cap",
            "cash_buffer",
            "industry_concentration",
            "account_drawdown_halt",
            "position_loss_alert",
        ],
        "limits": dict(DEFAULT_LIMITS),
    }


def is_ready() -> bool:
    required = {
        "single_position_cap",
        "gross_exposure_cap",
        "cash_buffer",
        "industry_concentration",
        "account_drawdown_halt",
    }
    return required <= set(capabilities()["supports"])


def evaluate_account_risk(
    account: dict[str, Any],
    *,
    industry_by_code: dict[str, str] | None = None,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Return alerts and a soft halt flag for recommendation paper accounts."""
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    industry_by_code = industry_by_code or {}
    equity = float(account.get("total_equity") or 0)
    initial = float(account.get("initial_cash") or 0)
    cash = float(account.get("cash") or 0)
    market_value = float(account.get("market_value") or 0)
    positions = account.get("positions") or {}
    alerts: list[dict[str, Any]] = []

    invested_weight = market_value / equity if equity > 0 else 0.0
    cash_weight = cash / equity if equity > 0 else 0.0
    if initial > 0 and equity / initial - 1 <= float(limits["account_drawdown_pct"]):
        alerts.append({
            "level": "high",
            "code": "account_drawdown",
            "message": f"账户回撤低于 {limits['account_drawdown_pct'] * 100:.0f}%",
        })
    if invested_weight > float(limits["max_invested_weight"]):
        alerts.append({
            "level": "medium",
            "code": "high_invested_weight",
            "message": f"总仓位超过 {limits['max_invested_weight'] * 100:.0f}%",
        })
    if cash_weight < float(limits["min_cash_weight"]):
        alerts.append({
            "level": "medium",
            "code": "low_cash_buffer",
            "message": f"现金缓冲低于 {limits['min_cash_weight'] * 100:.0f}%",
        })

    industry_weights: dict[str, float] = {}
    for code, pos in positions.items():
        shares = float(pos.get("shares") or 0)
        price = float(pos.get("last_price") or pos.get("avg_cost") or 0)
        weight = (shares * price / equity) if equity > 0 else 0.0
        if weight > float(limits["max_single_weight"]):
            alerts.append({
                "level": "high",
                "code": "single_position_concentration",
                "message": f"{code} 单票仓位超过 {limits['max_single_weight'] * 100:.0f}%",
            })
        unrealized_pct = float(pos.get("unrealized_pnl_pct") or 0)
        if unrealized_pct <= float(limits["position_loss_pct"]):
            alerts.append({
                "level": "high",
                "code": "position_loss",
                "message": f"{code} 浮亏超过 {limits['position_loss_pct']:.0f}%",
            })
        industry = industry_by_code.get(str(code)) or str(pos.get("industry") or "未分类")
        industry_weights[industry] = industry_weights.get(industry, 0.0) + weight

    for industry, weight in industry_weights.items():
        if industry != "未分类" and weight > float(limits["max_industry_weight"]):
            alerts.append({
                "level": "medium",
                "code": "industry_concentration",
                "message": f"{industry} 行业暴露超过 {limits['max_industry_weight'] * 100:.0f}%",
            })

    halt = any(row.get("level") == "high" and row.get("code") == "account_drawdown" for row in alerts)
    return {
        "version": PORTFOLIO_RISK_ENGINE_VERSION,
        "halt_new_entries": halt,
        "alerts": alerts,
        "metrics": {
            "invested_weight": round(invested_weight, 4),
            "cash_weight": round(cash_weight, 4),
            "industry_weights": {k: round(v, 4) for k, v in sorted(industry_weights.items())},
        },
    }
