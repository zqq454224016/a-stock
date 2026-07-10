"""组合管理测试。"""

from quant_system.portfolio.analyzer import build_portfolio_payload


def test_portfolio_reports_cash_and_target_positions_when_empty():
    payload = build_portfolio_payload(
        account={"initial_cash": 100000, "cash": 100000, "market_value": 0, "total_equity": 100000, "positions": {}},
        decisions={
            "600001": {"code": "600001", "name": "测试", "action": "buy", "position_suggestion": 0.12, "confidence": "medium", "requires_human_review": True}
        },
    )

    assert payload["summary"]["cash_weight"] == 1.0
    assert payload["summary"]["position_count"] == 0
    assert payload["summary"]["target_count"] == 1
    assert payload["target_positions"][0]["target_weight"] == 0.12
    assert payload["target_positions"][0]["requires_human_review"] is True


def test_portfolio_flags_single_position_concentration_and_target_exposure():
    payload = build_portfolio_payload(
        account={
            "initial_cash": 100000,
            "cash": 5000,
            "market_value": 95000,
            "total_equity": 100000,
            "positions": {
                "600001": {"code": "600001", "name": "测试A", "shares": 1000, "last_price": 30, "market_value": 30000, "avg_cost": 32, "unrealized_pnl_pct": -9},
                "000001": {"code": "000001", "name": "测试B", "shares": 1000, "last_price": 65, "market_value": 65000, "avg_cost": 60, "unrealized_pnl_pct": 8},
            },
        },
        decisions={
            "600001": {"action": "hold", "position_suggestion": 0.45},
            "000001": {"action": "hold", "position_suggestion": 0.45},
        },
    )

    codes = {x["code"] for x in payload["risk_alerts"]}
    assert "high_invested_weight" in codes
    assert "single_position_concentration" in codes
    assert "position_loss" in codes
    assert "target_exposure_high" in codes
    assert payload["exposures"]["by_market"]["SH"] == 0.3
    assert payload["exposures"]["by_market"]["SZ"] == 0.65


def test_portfolio_reports_style_exposure_and_rebalance_plan():
    payload = build_portfolio_payload(
        account={
            "initial_cash": 100000,
            "cash": 50000,
            "market_value": 50000,
            "total_equity": 100000,
            "positions": {
                "600001": {"code": "600001", "name": "测试A", "shares": 1000, "last_price": 50, "market_value": 50000},
            },
        },
        decisions={
            "600001": {"action": "hold", "position_suggestion": 0.2},
            "000001": {"action": "buy", "position_suggestion": 0.15, "requires_human_review": True},
        },
        stocks={
            "600001": {"name": "测试A", "industry": "化工", "analysis": {"returns": {"d20": 20}, "turnover": 9}},
            "000001": {"name": "测试B", "industry": "电子", "analysis": {"returns": {"d20": -3}}},
        },
        factors={
            "600001": {"factors": {"fundamental_detail": {"market_cap_yi": 800, "pe_ttm": 80, "pb": 9}}},
            "000001": {"factors": {"fundamental_detail": {"market_cap_yi": 80, "pe_ttm": 25, "pb": 2}}},
        },
        impacts={
            "600001": {"impact_score": -20},
            "000001": {"impact_score": 18},
        },
    )

    assert payload["positions"][0]["industry"] == "化工"
    assert "高估值" in payload["positions"][0]["styles"]
    assert payload["exposures"]["by_style"]["高估值"] == 0.5
    assert payload["exposures"]["target_by_industry"]["电子"] == 0.15
    assert payload["rebalance_plan"][0]["action"] in {"减配", "增配"}
