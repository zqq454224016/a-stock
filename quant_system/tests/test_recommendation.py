from __future__ import annotations

from quant_system.recommendation.builder import build_recommendation_payload


def _inputs(selector_status: str = "candidate") -> dict:
    code = "600001"
    return {
        "market": {
            "trade_date": "2026-07-09",
            "indices": [{"name": "上证指数", "change_pct": 1.0}],
            "fund_flow": {"main_net": 20},
        },
        "stocks": {
            code: {
                "code": code, "name": "测试股份",
                "quality": {"quality_score": 95},
                "analysis": {"returns": {"d5": 5, "d20": 12, "d60": 25}},
            }
        },
        "selectors": {
            code: {
                "upside_score": 88, "status": selector_status,
                "reject_reasons": ["风险门禁未通过"] if selector_status == "rejected" else [],
                "risks": [], "next_triggers": ["跌破20日均线"],
            }
        },
        "predictions": {code: {"direction": "up", "probability": 0.72}},
        "factors": {code: {"factors": {"multi_factor_score": 82, "technical_score": 80}}},
        "impacts": {code: {"impact_score": 20}},
        "enhances": {code: {"fundamentals": {"pe_ttm": 25, "pb": 3}}},
        "replays": {code: {"summary": {"hit_rate": 0.7}}},
    }


def test_build_recommendations_for_all_periods() -> None:
    payload = build_recommendation_payload(**_inputs(), limit=5)

    assert set(payload["periods"]) == {"short", "medium", "long"}
    assert all(len(x["recommendations"]) == 1 for x in payload["periods"].values())
    assert payload["periods"]["short"]["recommendations"][0]["replay_summary"]["hit_rate"] == 0.7
    assert payload["market_context"]["regime"] == "偏强"


def test_rejected_stock_is_not_forced_into_recommendations() -> None:
    payload = build_recommendation_payload(**_inputs("rejected"), limit=5)

    assert not payload["periods"]["short"]["recommendations"]
    assert payload["periods"]["short"]["shortage_count"] == 5
    assert "不为凑满5只而降低标准" in payload["periods"]["short"]["shortage_reason"]
    assert payload["periods"]["long"]["recommendations"]
