"""Recommendation-only execution simulator: T+1, limits, fees, slippage, partial fills.

No broker gateway. Orders stay in the local paper account and only validate that
recommendation-driven rebalances respect A-share constraints.
"""

from __future__ import annotations

from typing import Any

from quant_system.config.trading_config import EXECUTION_SIMULATOR_VERSION, TradingConfig
from quant_system.trading import order_state
from quant_system.trading.simulator import (
    _apply_target_rebalance,
    account_summary,
    apply_decision_rebalance,
    apply_prediction_rebalance,
    mark_to_market,
    new_account,
    trade_fee,
)

CAPABILITIES = (
    "t_plus_1",
    "price_limit_reject",
    "suspension_reject",
    "slippage",
    "partial_fill",
    "commission_and_stamp",
    "lot_size",
    "liquidity_cap",
)


def capabilities() -> dict[str, Any]:
    return {
        "version": EXECUTION_SIMULATOR_VERSION,
        "scope": "paper_recommendation_only",
        "broker_integration": False,
        "supports": list(CAPABILITIES),
        "order_state_machine": order_state.capabilities(),
        "fee_model": {
            "commission_rate": TradingConfig().commission_rate,
            "min_commission": TradingConfig().min_commission,
            "stamp_tax_rate": TradingConfig().stamp_tax_rate,
            "slippage_bps": TradingConfig().slippage_bps,
        },
    }


def is_ready() -> bool:
    caps = set(capabilities()["supports"])
    required = {
        "t_plus_1", "price_limit_reject", "suspension_reject",
        "slippage", "partial_fill", "commission_and_stamp",
    }
    return required <= caps and order_state.capabilities()["broker_integration"] is False


def build_tradability(
    *,
    suspended: bool = False,
    at_limit_up: bool = False,
    at_limit_down: bool = False,
    max_executable_shares: int = 0,
    st_risk: bool = False,
) -> dict[str, Any]:
    """Map market constraints into buy/sell reject reasons for the paper simulator."""
    buy_reject = ""
    sell_reject = ""
    if suspended:
        buy_reject = sell_reject = "suspended"
    else:
        if at_limit_up:
            buy_reject = "limit_up"
        if at_limit_down:
            sell_reject = "limit_down"
    if st_risk and not buy_reject:
        buy_reject = "st_risk_blocked"
    return {
        "buy_reject_reason": buy_reject,
        "sell_reject_reason": sell_reject,
        "max_executable_shares": int(max_executable_shares or 0),
        "suspended": suspended,
        "at_limit_up": at_limit_up,
        "at_limit_down": at_limit_down,
    }


def simulate_recommendation_rebalance(
    account: dict[str, Any] | None,
    *,
    code: str,
    name: str,
    price: float,
    target_pct: float,
    trade_date: str,
    tradability: dict[str, Any] | None = None,
    cfg: TradingConfig | None = None,
    reason: str = "recommendation",
) -> dict[str, Any]:
    """Apply a recommendation target weight through the paper execution path."""
    cfg = cfg or TradingConfig()
    account = account or new_account(cfg.initial_cash)
    action = "buy" if target_pct > 0 else "sell"
    return _apply_target_rebalance(
        account,
        code=code,
        price=price,
        target_pct=min(max(float(target_pct), 0.0), cfg.max_position_pct),
        name=name,
        cfg=cfg,
        reason=reason,
        decision_action=action,
        trade_date=trade_date,
        tradability=tradability,
    )


__all__ = [
    "CAPABILITIES",
    "account_summary",
    "apply_decision_rebalance",
    "apply_prediction_rebalance",
    "build_tradability",
    "capabilities",
    "is_ready",
    "mark_to_market",
    "new_account",
    "simulate_recommendation_rebalance",
    "trade_fee",
]
