from __future__ import annotations

from quant_system.contracts import build_framework_snapshot


def test_framework_snapshot_adapts_existing_module_outputs() -> None:
    code = "600001"
    payload = build_framework_snapshot(
        stocks={code: {"name": "测试股份", "quality": {"quality_score": 95}, "trade_date": "2026-07-10"}},
        predictions={code: {"direction": "up", "probability": 0.71, "confidence": "high", "horizon": "5d"}},
        selectors={code: {"status": "candidate", "upside_score": 82, "reasons": ["因子较强"]}},
        decisions={code: {"action": "buy", "position_suggestion": 0.3, "confidence": "medium", "reasons": ["预测偏多"]}},
        impacts={code: {"impact_direction": "positive", "impact_score": 20, "events": [{"event_type": "业绩", "title": "利润增长"}]}},
        replays={code: {"summary": {"hit_rate": 0.6}}},
        recommendations={"periods": {"short": {"evaluated": [{"code": code, "status": "recommended", "score": 75, "horizon": "1-5个交易日"}]}}},
    )

    assert payload["coverage"]["universe_count"] == 1
    assert payload["coverage"]["signal_count"] == 3
    assert {x["source"] for x in payload["signals"]} == {"prediction", "selector", "recommendation.short"}
    assert payload["risk_checks"][0]["passed"] is True
    assert payload["execution_intents"][0]["allowed"] is True
    assert payload["execution_intents"][0]["requires_human_review"] is True
    assert {x["topic"] for x in payload["analysis_findings"]} == {"十日推演", "实际影响"}


def test_framework_snapshot_blocks_low_quality_universe_member() -> None:
    code = "600002"
    payload = build_framework_snapshot(
        stocks={code: {"name": "低质股份", "quality": {"quality_score": 60}}},
        predictions={},
        selectors={code: {"status": "rejected", "upside_score": 30, "reject_reasons": ["预测偏空"]}},
        decisions={},
        impacts={},
        replays={},
        recommendations={},
    )

    assert payload["universe"][0]["is_tradeable"] is False
    assert payload["risk_checks"][0]["passed"] is False
    assert "数据质量低于70分" in payload["risk_checks"][0]["blockers"]
    assert payload["execution_intents"][0]["allowed"] is False
