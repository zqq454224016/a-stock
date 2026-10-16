"""Paper execution simulator for recommendation-only mode."""

from quant_system.trading.execution_simulator import (
    build_tradability,
    capabilities,
    is_ready,
    new_account,
    simulate_recommendation_rebalance,
)
from quant_system.trading.order_state import can_transition, resolve_fill_status, transition
from quant_system.trading.portfolio_risk import evaluate_account_risk, is_ready as risk_ready


def test_execution_simulator_declares_required_capabilities():
    caps = capabilities()
    assert caps["broker_integration"] is False
    assert caps["scope"] == "paper_recommendation_only"
    assert is_ready()
    for name in ("t_plus_1", "partial_fill", "slippage", "commission_and_stamp"):
        assert name in caps["supports"]


def test_limit_up_rejects_buy():
    account = new_account(50_000)
    account = simulate_recommendation_rebalance(
        account,
        code="600000",
        name="浦发银行",
        price=10.0,
        target_pct=0.1,
        trade_date="2026-10-16",
        tradability=build_tradability(at_limit_up=True),
    )
    assert account["orders"][-1]["status"] == "rejected"
    assert account["orders"][-1]["reject_reason"] == "limit_up"
    assert "600000" not in account["positions"]


def test_partial_fill_when_liquidity_capped():
    account = new_account(50_000)
    account = simulate_recommendation_rebalance(
        account,
        code="600000",
        name="浦发银行",
        price=10.0,
        target_pct=0.2,
        trade_date="2026-10-16",
        tradability=build_tradability(max_executable_shares=200),
    )
    order = account["orders"][-1]
    assert order["status"] == "partial"
    assert order["filled_shares"] == 200
    assert order["requested_shares"] > 200
    assert account["positions"]["600000"]["shares"] == 200


def test_order_state_transitions_and_risk_engine():
    assert can_transition("pending", "accepted")
    assert not can_transition("filled", "pending")
    assert resolve_fill_status(requested_shares=500, filled_shares=200) == "partial"
    order = transition({"status": "pending"}, "accepted")
    order = transition(order, "partial")
    assert order["status"] == "partial"
    assert risk_ready()
    account = new_account(50_000)
    account["positions"]["600000"] = {
        "shares": 2000, "avg_cost": 10, "last_price": 10, "unrealized_pnl_pct": 0,
    }
    account["market_value"] = 20_000
    account["total_equity"] = 50_000
    account["cash"] = 30_000
    report = evaluate_account_risk(account, industry_by_code={"600000": "银行"})
    assert "alerts" in report
