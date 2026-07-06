"""模拟交易测试（P3-1）。"""

from quant_system.config.trading_config import TradingConfig
from quant_system.trading.simulator import (
    account_summary,
    apply_decision_rebalance,
    apply_prediction_rebalance,
    mark_to_market,
    new_account,
    target_position_pct,
)


def test_target_position_pct_requires_bullish_prediction():
    cfg = TradingConfig(max_position_pct=0.2, min_buy_probability=0.55)
    assert target_position_pct({"direction": "down", "probability": 0.4, "confidence": "high"}, cfg) == 0.0
    assert target_position_pct({"direction": "up", "probability": 0.54, "confidence": "high"}, cfg) == 0.0
    assert target_position_pct({"direction": "up", "probability": 0.75, "confidence": "high"}, cfg) == 0.2


def test_apply_prediction_rebalance_buys_lot_shares():
    cfg = TradingConfig(initial_cash=100_000, max_position_pct=0.2, min_buy_probability=0.55)
    account = new_account(cfg.initial_cash)
    pred = {"code": "600378", "direction": "up", "probability": 0.75, "confidence": "high"}

    account = apply_prediction_rebalance(account, pred, price=50.0, name="昊华科技", cfg=cfg)

    pos = account["positions"]["600378"]
    assert pos["shares"] == 300
    assert account["cash"] < 100_000
    assert len(account["orders"]) == 1
    assert account["orders"][0]["side"] == "buy"


def test_apply_prediction_rebalance_sells_when_prediction_turns_down():
    cfg = TradingConfig(initial_cash=100_000, max_position_pct=0.2, min_buy_probability=0.55)
    account = new_account(cfg.initial_cash)
    buy = {"code": "600378", "direction": "up", "probability": 0.75, "confidence": "high"}
    sell = {"code": "600378", "direction": "down", "probability": 0.4, "confidence": "high"}

    account = apply_prediction_rebalance(account, buy, price=50.0, name="昊华科技", cfg=cfg)
    account = apply_prediction_rebalance(account, sell, price=52.0, name="昊华科技", cfg=cfg)

    assert "600378" not in account["positions"]
    assert len(account["orders"]) == 2
    assert account["orders"][-1]["side"] == "sell"
    assert account["realized_pnl"] > 0


def test_mark_to_market_updates_summary():
    account = new_account(100_000)
    account["positions"]["600378"] = {
        "code": "600378",
        "name": "昊华科技",
        "shares": 100,
        "avg_cost": 50.0,
    }
    account = mark_to_market(account, {"600378": 55.0})
    summary = account_summary(account)

    assert account["market_value"] == 5500.0
    assert account["positions"]["600378"]["unrealized_pnl"] == 500.0
    assert summary["position_count"] == 1


def test_apply_decision_rebalance_uses_position_suggestion_directly():
    cfg = TradingConfig(initial_cash=100_000, max_position_pct=0.2)
    account = new_account(cfg.initial_cash)
    decision = {
        "code": "600378",
        "action": "buy",
        "position_suggestion": 0.12,
        "confidence": "medium",
        "evidence": {"prediction": {"probability": 0.59}},
    }
    account = apply_decision_rebalance(account, decision, price=50.0, name="昊华科技", cfg=cfg)

    pos = account["positions"]["600378"]
    assert pos["shares"] == 200
    assert account["orders"][0]["reason"] == "decision_buy_medium"
    assert account["orders"][0]["decision_action"] == "buy"
