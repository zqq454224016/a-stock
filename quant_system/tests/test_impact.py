"""实际影响数据提取测试。"""

from quant_system.impact.builder import build_impact_payload


def test_litong_q2_profit_gap_is_marked_when_q2_data_missing():
    payload = build_impact_payload(
        "603629",
        "利通电子",
        {
            "corporate": {
                "earnings_forecast": {
                    "forecast_type": "预增",
                    "change_pct": 1118.7,
                    "forecast_value": 300000000.0,
                    "indicator": "归属于上市公司股东的净利润",
                    "reason": "业绩预增的原因主要是算力业务端盈利增加、制造端业务亏损收窄。",
                    "announce_date": "2026-01-27",
                    "report_period": "20251231",
                }
            },
            "fundamentals": {"pe_ttm": 81.78, "pb": 19.47},
        },
    )

    event_types = {e["event_type"] for e in payload["events"]}
    assert "earnings_forecast" in event_types
    assert "q2_profit_growth_gap" in event_types
    assert "requires_q2_official_report_or_forecast" in payload["limitations"]
    assert payload["evidence_quality"]["low_quality_event_count"] >= 1


def test_haohua_material_price_reason_creates_positive_event():
    payload = build_impact_payload(
        "600378",
        "昊华科技",
        {
            "corporate": {
                "earnings_forecast": {
                    "forecast_type": "预增",
                    "change_pct": 67.805,
                    "forecast_value": 310000000.0,
                    "reason": "氟化工业务一体化管理效能显著，在制冷剂产品市场价格维持高位运行，锂电业务市场复苏。",
                    "announce_date": "2026-04-20",
                    "report_period": "20260331",
                }
            },
        },
    )

    material = [e for e in payload["events"] if e["event_type"] == "material_or_product_price"]
    assert material
    assert material[0]["impact_direction"] == "positive"
    assert material[0]["impact_score"] > 0
    assert material[0]["evidence_quality"]["level"] in {"medium", "high"}


def test_high_valuation_creates_negative_pressure_event():
    payload = build_impact_payload(
        "603629",
        "利通电子",
        {"fundamentals": {"pe_ttm": 90, "pb": 12}},
    )

    valuation = [e for e in payload["events"] if e["event_type"] == "valuation_pressure"]
    assert valuation
    assert valuation[0]["impact_direction"] == "negative"


def test_past_lockup_is_not_current_negative_event():
    payload = build_impact_payload(
        "000988",
        "华工科技",
        {"corporate": {"lockups": [{"unlock_date": "2018-12-10", "unlock_value_yi": 13.54, "pct_float": 0.11}]}},
    )

    assert not [e for e in payload["events"] if e["event_type"] == "lockup_pressure"]


def test_impact_payload_contains_post_event_review_summary():
    payload = build_impact_payload(
        "600001",
        "测试股票",
        {"fundamentals": {"pe_ttm": 90, "pb": 12}},
        review={
            "summary": {
                "evaluated_count": 3,
                "pending_count": 0,
                "hit_rate": 0.67,
                "avg_return_pct": 2.4,
                "worst_adverse_pct": -1.2,
            }
        },
    )

    assert payload["post_event_review"]["status"] == "evaluated"
    assert payload["post_event_review"]["hit_rate"] == 0.67
