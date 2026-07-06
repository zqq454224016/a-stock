"""模拟交易引擎（P3-1）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from quant_system.config.trading_config import SIM_TRADING_VERSION, TradingConfig
from quant_system.utils.time_utils import now_str


def new_account(initial_cash: float, updated_at: str | None = None) -> dict[str, Any]:
    return {
        "version": SIM_TRADING_VERSION,
        "updated_at": updated_at or now_str(),
        "initial_cash": round(float(initial_cash), 2),
        "cash": round(float(initial_cash), 2),
        "market_value": 0.0,
        "total_equity": round(float(initial_cash), 2),
        "positions": {},
        "orders": [],
        "trades": [],
        "realized_pnl": 0.0,
    }


def target_position_pct(prediction: dict[str, Any], cfg: TradingConfig) -> float:
    direction = prediction.get("direction")
    confidence = prediction.get("confidence", "low")
    probability = float(prediction.get("probability") or 0)

    if direction != "up" or probability < cfg.min_buy_probability:
        return 0.0

    confidence_weight = {"high": 1.0, "medium": 0.7, "low": 0.35}.get(confidence, 0.35)
    strength = min(max((probability - cfg.min_buy_probability) / 0.20, 0.25), 1.0)
    return round(cfg.max_position_pct * confidence_weight * strength, 4)


def trade_fee(amount: float, side: str, cfg: TradingConfig) -> float:
    commission = max(amount * cfg.commission_rate, cfg.min_commission)
    stamp = amount * cfg.stamp_tax_rate if side == "sell" else 0.0
    slippage = amount * cfg.slippage_bps / 10_000
    return round(commission + stamp + slippage, 2)


def execution_price(price: float, side: str, cfg: TradingConfig) -> float:
    slip = cfg.slippage_bps / 10_000
    if side == "buy":
        return round(price * (1 + slip), 4)
    return round(price * (1 - slip), 4)


def _round_lot(shares: float, lot_size: int) -> int:
    return int(shares // lot_size) * lot_size


def _position_value(pos: dict[str, Any], price: float) -> float:
    return float(pos.get("shares") or 0) * price


def _apply_target_rebalance(
    account: dict[str, Any],
    *,
    code: str,
    price: float,
    target_pct: float,
    name: str,
    cfg: TradingConfig,
    reason: str,
    prediction_probability: Any = None,
    decision_action: str | None = None,
) -> dict[str, Any]:
    account = mark_to_market(account, {code: price})
    positions = account.setdefault("positions", {})
    pos = positions.get(code, {"code": code, "name": name, "shares": 0, "avg_cost": 0.0})

    equity = float(account.get("total_equity") or cfg.initial_cash)
    target_value = equity * target_pct
    current_value = _position_value(pos, price)
    delta_value = target_value - current_value

    if abs(delta_value) < cfg.min_trade_amount:
        return account

    side = "buy" if delta_value > 0 else "sell"
    exec_px = execution_price(price, side, cfg)
    raw_shares = abs(delta_value) / exec_px if exec_px > 0 else 0
    shares = _round_lot(raw_shares, cfg.lot_size)

    if side == "sell":
        shares = min(shares, int(pos.get("shares") or 0))
    if shares <= 0:
        return account

    amount = round(exec_px * shares, 2)
    fee = trade_fee(amount, side, cfg)

    if side == "buy":
        max_affordable = _round_lot((float(account["cash"]) - fee) / exec_px, cfg.lot_size)
        shares = min(shares, max_affordable)
        if shares <= 0:
            return account
        amount = round(exec_px * shares, 2)
        fee = trade_fee(amount, side, cfg)
        total_cost = amount + fee
        if total_cost > float(account["cash"]):
            return account

        old_shares = int(pos.get("shares") or 0)
        old_cost = float(pos.get("avg_cost") or 0) * old_shares
        new_shares = old_shares + shares
        pos["avg_cost"] = round((old_cost + total_cost) / new_shares, 4)
        pos["shares"] = new_shares
        pos["name"] = name or pos.get("name", "")
        account["cash"] = round(float(account["cash"]) - total_cost, 2)
        realized = 0.0
    else:
        old_shares = int(pos.get("shares") or 0)
        avg_cost = float(pos.get("avg_cost") or 0)
        proceeds = amount - fee
        pos["shares"] = old_shares - shares
        realized = round(proceeds - avg_cost * shares, 2)
        account["cash"] = round(float(account["cash"]) + proceeds, 2)
        account["realized_pnl"] = round(float(account.get("realized_pnl") or 0) + realized, 2)

    order = {
        "code": code,
        "name": name or pos.get("name", ""),
        "side": side,
        "shares": shares,
        "price": exec_px,
        "amount": amount,
        "fee": fee,
        "status": "filled",
        "reason": reason,
        "target_position_pct": round(target_pct, 4),
        "prediction_probability": prediction_probability,
        "created_at": now_str(),
    }
    if decision_action:
        order["decision_action"] = decision_action
    trade = {**order, "realized_pnl": realized}

    account.setdefault("orders", []).append(order)
    account.setdefault("trades", []).append(trade)
    if int(pos.get("shares") or 0) > 0:
        positions[code] = pos
    else:
        positions.pop(code, None)

    return mark_to_market(account, {code: price})


def mark_to_market(account: dict[str, Any], prices: dict[str, float]) -> dict[str, Any]:
    account = deepcopy(account)
    positions = account.setdefault("positions", {})
    market_value = 0.0

    for code, pos in list(positions.items()):
        shares = int(pos.get("shares") or 0)
        if shares <= 0:
            positions.pop(code, None)
            continue
        price = float(prices.get(code) or pos.get("last_price") or pos.get("avg_cost") or 0)
        value = round(shares * price, 2)
        avg_cost = float(pos.get("avg_cost") or 0)
        cost = avg_cost * shares
        pos["last_price"] = price
        pos["market_value"] = value
        pos["unrealized_pnl"] = round(value - cost, 2)
        pos["unrealized_pnl_pct"] = round((value / cost - 1) * 100, 2) if cost > 0 else 0.0
        market_value += value

    account["market_value"] = round(market_value, 2)
    account["total_equity"] = round(float(account.get("cash") or 0) + market_value, 2)
    account["updated_at"] = now_str()
    return account


def apply_prediction_rebalance(
    account: dict[str, Any],
    prediction: dict[str, Any],
    *,
    price: float,
    name: str = "",
    cfg: TradingConfig | None = None,
) -> dict[str, Any]:
    """根据单只股票预测调整虚拟仓位。"""
    cfg = cfg or TradingConfig()
    code = prediction["code"]
    target_pct = target_position_pct(prediction, cfg)
    return _apply_target_rebalance(
        account,
        code=code,
        price=price,
        target_pct=target_pct,
        name=name,
        cfg=cfg,
        reason=f"prediction_{prediction.get('direction')}_{prediction.get('confidence')}",
        prediction_probability=prediction.get("probability"),
    )


def apply_decision_rebalance(
    account: dict[str, Any],
    decision: dict[str, Any],
    *,
    price: float,
    name: str = "",
    cfg: TradingConfig | None = None,
) -> dict[str, Any]:
    """根据单股决策建议调整虚拟仓位。"""
    cfg = cfg or TradingConfig()
    code = decision["code"]
    action = decision.get("action", "watch")
    suggestion = float(decision.get("position_suggestion") or 0.0)

    if action in ("watch", "sell"):
        target_pct = 0.0
    elif action == "reduce":
        target_pct = min(suggestion, cfg.max_position_pct / 2)
    elif action in ("buy", "hold"):
        target_pct = min(suggestion, cfg.max_position_pct)
    else:
        target_pct = 0.0

    return _apply_target_rebalance(
        account,
        code=code,
        price=price,
        target_pct=target_pct,
        name=name,
        cfg=cfg,
        reason=f"decision_{action}_{decision.get('confidence')}",
        prediction_probability=decision.get("evidence", {}).get("prediction", {}).get("probability"),
        decision_action=action,
    )


def account_summary(account: dict[str, Any]) -> dict[str, Any]:
    initial = float(account.get("initial_cash") or 0)
    equity = float(account.get("total_equity") or 0)
    return {
        "updated_at": account.get("updated_at"),
        "initial_cash": round(initial, 2),
        "cash": account.get("cash", 0),
        "market_value": account.get("market_value", 0),
        "total_equity": round(equity, 2),
        "total_return_pct": round((equity / initial - 1) * 100, 2) if initial > 0 else 0.0,
        "position_count": len(account.get("positions") or {}),
        "order_count": len(account.get("orders") or []),
        "trade_count": len(account.get("trades") or []),
        "realized_pnl": account.get("realized_pnl", 0),
    }
