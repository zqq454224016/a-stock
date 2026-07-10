"""账户组合视角分析。"""

from __future__ import annotations

from typing import Any

PORTFOLIO_VERSION = "1.1.0"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _market_from_code(code: str) -> str:
    if code.startswith(("60", "68", "69")):
        return "SH"
    if code.startswith(("00", "30")):
        return "SZ"
    if code.startswith(("43", "83", "87", "92")):
        return "BJ"
    return "UNKNOWN"


def _pick_nested(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", {}):
            return value
    return None


def _stock_profile(
    code: str,
    stocks: dict[str, dict[str, Any]],
    factors: dict[str, dict[str, Any]],
    enhances: dict[str, dict[str, Any]],
    impacts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stock = stocks.get(code) or {}
    factor_payload = factors.get(code) or {}
    factor = factor_payload.get("factors") or {}
    enhance = enhances.get(code) or {}
    fundamentals = enhance.get("fundamentals") or {}
    detail = factor.get("fundamental_detail") or {}
    impact = impacts.get(code) or {}
    analysis = stock.get("analysis") or {}
    returns = analysis.get("returns") or {}

    industry = _pick_nested(
        stock.get("industry"),
        fundamentals.get("industry"),
        enhance.get("industry"),
        "行业待分类",
    )
    market_cap = _to_float(_pick_nested(detail.get("market_cap_yi"), fundamentals.get("market_cap_yi")))
    pe = _to_float(_pick_nested(detail.get("pe_ttm"), fundamentals.get("pe_ttm")))
    pb = _to_float(_pick_nested(detail.get("pb"), fundamentals.get("pb")))
    momentum_20 = _to_float(_pick_nested(factor.get("momentum_20"), returns.get("d20")))
    d5 = _to_float(returns.get("d5"))
    turnover = _to_float(analysis.get("turnover"))
    impact_score = _to_float(impact.get("impact_score"))

    styles: list[str] = []
    if market_cap >= 500:
        styles.append("大市值")
    elif market_cap >= 100:
        styles.append("中市值")
    elif market_cap > 0:
        styles.append("小市值")
    else:
        styles.append("市值缺失")

    if pe > 60 or pb > 8:
        styles.append("高估值")
    elif pe > 0 and pe < 35 and pb > 0 and pb < 4:
        styles.append("估值相对合理")
    else:
        styles.append("估值中性")

    if momentum_20 >= 15:
        styles.append("强动量")
    elif momentum_20 <= -10:
        styles.append("弱动量")
    else:
        styles.append("动量中性")

    if abs(d5) >= 10 or turnover >= 8:
        styles.append("高波动")
    if impact_score >= 15:
        styles.append("事件正面")
    elif impact_score <= -15:
        styles.append("事件负面")

    return {
        "industry": str(industry),
        "styles": styles,
        "metrics": {
            "market_cap_yi": market_cap,
            "pe_ttm": pe,
            "pb": pb,
            "momentum_20": momentum_20,
            "d5": d5,
            "turnover": turnover,
            "impact_score": impact_score,
        },
    }


def _decision_target(decision: dict[str, Any] | None) -> float:
    if not decision:
        return 0.0
    action = decision.get("action")
    if action in ("watch", "sell"):
        return 0.0
    return max(0.0, _to_float(decision.get("position_suggestion")))


def _position_rows(
    account: dict[str, Any],
    stocks: dict[str, dict[str, Any]] | None,
    decisions: dict[str, dict[str, Any]] | None,
    factors: dict[str, dict[str, Any]] | None,
    enhances: dict[str, dict[str, Any]] | None,
    impacts: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    stocks = stocks or {}
    decisions = decisions or {}
    factors = factors or {}
    enhances = enhances or {}
    impacts = impacts or {}
    equity = _to_float(account.get("total_equity"))
    rows: list[dict[str, Any]] = []
    for code, pos in sorted((account.get("positions") or {}).items()):
        value = _to_float(pos.get("market_value"))
        weight = value / equity if equity > 0 else 0.0
        decision = decisions.get(code) or {}
        target = _decision_target(decision)
        profile = _stock_profile(code, stocks, factors, enhances, impacts)
        rows.append({
            "code": code,
            "name": pos.get("name") or (stocks.get(code) or {}).get("name") or code,
            "market": _market_from_code(code),
            "industry": profile["industry"],
            "styles": profile["styles"],
            "style_metrics": profile["metrics"],
            "shares": int(pos.get("shares") or 0),
            "last_price": _to_float(pos.get("last_price")),
            "market_value": round(value, 2),
            "weight": round(weight, 4),
            "avg_cost": _to_float(pos.get("avg_cost")),
            "unrealized_pnl": _to_float(pos.get("unrealized_pnl")),
            "unrealized_pnl_pct": _to_float(pos.get("unrealized_pnl_pct")),
            "decision_action": decision.get("action"),
            "target_weight": round(target, 4),
            "rebalance_gap": round(target - weight, 4),
        })
    return rows


def _target_rows(
    account: dict[str, Any],
    stocks: dict[str, dict[str, Any]] | None,
    decisions: dict[str, dict[str, Any]] | None,
    factors: dict[str, dict[str, Any]] | None,
    enhances: dict[str, dict[str, Any]] | None,
    impacts: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    stocks = stocks or {}
    decisions = decisions or {}
    factors = factors or {}
    enhances = enhances or {}
    impacts = impacts or {}
    equity = _to_float(account.get("total_equity"))
    current = {
        code: _to_float(pos.get("market_value")) / equity
        for code, pos in (account.get("positions") or {}).items()
        if equity > 0
    }
    rows: list[dict[str, Any]] = []
    for code, decision in sorted(decisions.items()):
        target = _decision_target(decision)
        if target <= 0 and code not in current:
            continue
        stock = stocks.get(code) or {}
        weight = current.get(code, 0.0)
        profile = _stock_profile(code, stocks, factors, enhances, impacts)
        rows.append({
            "code": code,
            "name": decision.get("name") or stock.get("name") or code,
            "market": _market_from_code(code),
            "industry": profile["industry"],
            "styles": profile["styles"],
            "style_metrics": profile["metrics"],
            "decision_action": decision.get("action"),
            "decision_confidence": decision.get("confidence"),
            "current_weight": round(weight, 4),
            "target_weight": round(target, 4),
            "rebalance_gap": round(target - weight, 4),
            "requires_human_review": bool(decision.get("requires_human_review")),
        })
    return rows


def _exposures(positions: list[dict[str, Any]], target_rows: list[dict[str, Any]], cash_weight: float) -> dict[str, Any]:
    by_market: dict[str, float] = {}
    target_by_market: dict[str, float] = {}
    by_industry: dict[str, float] = {}
    target_by_industry: dict[str, float] = {}
    by_style: dict[str, float] = {}
    target_by_style: dict[str, float] = {}
    for row in positions:
        weight = _to_float(row.get("weight"))
        by_market[row["market"]] = by_market.get(row["market"], 0.0) + weight
        by_industry[row["industry"]] = by_industry.get(row["industry"], 0.0) + weight
        for style in row.get("styles") or []:
            by_style[style] = by_style.get(style, 0.0) + weight
    for row in target_rows:
        target = _to_float(row.get("target_weight"))
        target_by_market[row["market"]] = target_by_market.get(row["market"], 0.0) + target
        target_by_industry[row["industry"]] = target_by_industry.get(row["industry"], 0.0) + target
        for style in row.get("styles") or []:
            target_by_style[style] = target_by_style.get(style, 0.0) + target
    return {
        "cash_weight": round(cash_weight, 4),
        "by_market": {k: round(v, 4) for k, v in sorted(by_market.items())},
        "target_by_market": {k: round(v, 4) for k, v in sorted(target_by_market.items())},
        "by_industry": {k: round(v, 4) for k, v in sorted(by_industry.items())},
        "target_by_industry": {k: round(v, 4) for k, v in sorted(target_by_industry.items())},
        "by_style": {k: round(v, 4) for k, v in sorted(by_style.items())},
        "target_by_style": {k: round(v, 4) for k, v in sorted(target_by_style.items())},
        "top_positions": sorted(positions, key=lambda x: x.get("weight", 0), reverse=True)[:5],
    }


def _risk_alerts(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    exposures: dict[str, Any],
) -> list[dict[str, Any]]:
    equity = _to_float(account.get("total_equity"))
    initial = _to_float(account.get("initial_cash"))
    cash = _to_float(account.get("cash"))
    market_value = _to_float(account.get("market_value"))
    alerts: list[dict[str, Any]] = []
    cash_weight = cash / equity if equity > 0 else 0.0
    invested_weight = market_value / equity if equity > 0 else 0.0
    if equity <= 0:
        alerts.append({"level": "high", "code": "invalid_equity", "message": "账户权益无效"})
    if initial > 0 and equity / initial - 1 <= -0.1:
        alerts.append({"level": "high", "code": "account_drawdown", "message": "账户收益低于 -10%，需要停止加仓并复盘"})
    if invested_weight > 0.8:
        alerts.append({"level": "medium", "code": "high_invested_weight", "message": "持仓市值超过账户权益 80%"})
    if cash_weight < 0.1 and target_rows:
        alerts.append({"level": "medium", "code": "low_cash_buffer", "message": "现金缓冲低于 10%，新增买入需谨慎"})
    for row in positions:
        if _to_float(row.get("weight")) > 0.25:
            alerts.append({"level": "high", "code": "single_position_concentration", "message": f"{row['code']} 单票集中度超过 25%"})
        if _to_float(row.get("unrealized_pnl_pct")) <= -8:
            alerts.append({"level": "high", "code": "position_loss", "message": f"{row['code']} 浮亏超过 8%"})
    target_sum = sum(_to_float(row.get("target_weight")) for row in target_rows)
    if target_sum > 0.8:
        alerts.append({"level": "medium", "code": "target_exposure_high", "message": "目标总仓位超过 80%，需要组合级审批"})
    for industry, weight in (exposures.get("target_by_industry") or {}).items():
        if industry != "行业待分类" and _to_float(weight) > 0.45:
            alerts.append({"level": "medium", "code": "industry_concentration", "message": f"{industry} 目标行业暴露超过 45%"})
    for style, weight in (exposures.get("target_by_style") or {}).items():
        if style in {"高估值", "强动量", "高波动", "事件负面"} and _to_float(weight) > 0.55:
            alerts.append({"level": "medium", "code": "style_concentration", "message": f"{style}目标风格暴露超过 55%"})
    if sum(abs(_to_float(row.get("rebalance_gap"))) for row in target_rows) > 0.4:
        alerts.append({"level": "medium", "code": "rebalance_turnover_high", "message": "建议调仓幅度合计超过 40%，需要分批执行"})
    return alerts


def _rebalance_plan(target_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for row in target_rows:
        gap = _to_float(row.get("rebalance_gap"))
        if abs(gap) < 0.01:
            action = "保持"
        elif gap > 0:
            action = "增配"
        else:
            action = "减配"
        plan.append({
            "code": row.get("code"),
            "name": row.get("name"),
            "action": action,
            "rebalance_gap": round(gap, 4),
            "priority": "高" if abs(gap) >= 0.1 else "中" if abs(gap) >= 0.03 else "低",
            "requires_human_review": bool(row.get("requires_human_review")) or abs(gap) >= 0.1,
            "reason": f"当前 {_to_float(row.get('current_weight')) * 100:.1f}%，目标 {_to_float(row.get('target_weight')) * 100:.1f}%",
        })
    return sorted(plan, key=lambda x: abs(_to_float(x.get("rebalance_gap"))), reverse=True)


def build_portfolio_payload(
    *,
    account: dict[str, Any] | None,
    stocks: dict[str, dict[str, Any]] | None = None,
    decisions: dict[str, dict[str, Any]] | None = None,
    factors: dict[str, dict[str, Any]] | None = None,
    enhances: dict[str, dict[str, Any]] | None = None,
    impacts: dict[str, dict[str, Any]] | None = None,
    updated_at: str = "",
) -> dict[str, Any]:
    account = account or {}
    equity = _to_float(account.get("total_equity"))
    cash = _to_float(account.get("cash"))
    market_value = _to_float(account.get("market_value"))
    initial = _to_float(account.get("initial_cash"))
    positions = _position_rows(account, stocks, decisions, factors, enhances, impacts)
    target_rows = _target_rows(account, stocks, decisions, factors, enhances, impacts)
    cash_weight = cash / equity if equity > 0 else 0.0
    exposures = _exposures(positions, target_rows, cash_weight)
    alerts = _risk_alerts(account, positions, target_rows, exposures)
    rebalance_plan = _rebalance_plan(target_rows)
    return {
        "portfolio_version": PORTFOLIO_VERSION,
        "updated_at": updated_at or account.get("updated_at") or "",
        "summary": {
            "initial_cash": round(initial, 2),
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "total_equity": round(equity, 2),
            "total_return_pct": round((equity / initial - 1) * 100, 2) if initial > 0 else 0.0,
            "cash_weight": round(cash_weight, 4),
            "invested_weight": round(market_value / equity, 4) if equity > 0 else 0.0,
            "position_count": len(positions),
            "target_count": len(target_rows),
            "rebalance_count": len([x for x in rebalance_plan if x.get("action") != "保持"]),
            "risk_alert_count": len(alerts),
        },
        "positions": positions,
        "target_positions": target_rows,
        "rebalance_plan": rebalance_plan,
        "exposures": exposures,
        "risk_alerts": alerts,
        "limitations": [
            "industry_exposure_requires_industry_classification_data",
            "portfolio_uses_simtrade_account_until_live_account_is_connected",
        ],
    }
