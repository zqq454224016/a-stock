import json

from quant_system.ai import long_term_research


def test_long_evidence_is_bounded_and_excludes_permission_boards(tmp_path):
    stocks = tmp_path / "stocks"
    stocks.mkdir()
    for code, name in (("600001", "主板一"), ("000002", "主板二")):
        (stocks / f"{code}.json").write_text(json.dumps({
            "code": code, "name": name, "trade_date": "2026-08-11",
            "analysis": {"returns": {"d60": 5}, "ma": {"ma20": 10}},
        }), encoding="utf-8")
    ranked = {"periods": {"long": {"evaluated": [
        {"code": "688001", "name": "科创", "score": 99},
        {"code": "600001", "name": "主板一", "score": 80},
        {"code": "000002", "name": "主板二", "score": 79},
    ]}}}
    evidence = long_term_research.build_long_term_evidence(ranked, tmp_path, candidate_limit=1)
    assert [row["code"] for row in evidence["candidate_scope"]] == ["600001"]
    assert evidence["execution_allowed"] is False
    assert evidence["used_in_formal_score"] is False
    assert evidence["required_dimensions"] == ["market", "fundamental", "technical", "logic", "sentiment"]


def test_ai_result_rejects_unknown_symbol_and_caps_missing_fundamentals(tmp_path):
    evidence = {
        "market_context": {"trade_date": "2026-08-11"},
        "candidate_scope": [{"code": "600001", "name": "主板一"}],
        "candidate_metrics": {"600001": {"interim_report_context": {"status": "missing"}}},
    }
    raw = {"recommendations": [
        {"code": "999999", "confidence": 100},
        {"code": "600001", "confidence": 90, "thesis": "研究逻辑", "risks": ["风险"]},
    ]}
    result = long_term_research._validate_result(raw, evidence)
    assert [row["code"] for row in result["recommendations"]] == ["600001"]
    assert result["recommendations"][0]["confidence"] == 55
    assert "fundamental" in result["recommendations"][0]["missing_data"]
    assert result["execution_allowed"] is False


def test_extract_json_accepts_fence():
    value = long_term_research._extract_json('```json\n{"recommendations": []}\n```')
    assert value == {"recommendations": []}
