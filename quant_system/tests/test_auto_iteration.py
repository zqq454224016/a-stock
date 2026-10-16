import json

from quant_system.iteration.auto_iteration import build_iteration_status


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_auto_iteration_blocks_promotion_when_data_and_validation_fail(tmp_path):
    _write(tmp_path, "quality/latest.json", {
        "total": 2,
        "summary": {"ok": 2},
        "stocks": [{"rows": 250}, {"rows": 240}],
    })
    _write(tmp_path, "universe/stocks.json", {"count": 2500, "stocks": [{}] * 2500})
    _write(tmp_path, "interim_reports/index.json", {"status": "unavailable"})
    _write(tmp_path, "strategy_backtest/index.json", {"items": [{
        "20d": {
            "sample_count": 120,
            "hit_rate": 0.50,
            "avg_signed_return_pct": -0.2,
            "max_adverse_pct": -12,
        },
    }]})

    payload = build_iteration_status(tmp_path, tmp_path)

    assert payload["phase"] == "data_foundation"
    assert payload["strategy_status"] == "research_only"
    assert payload["promotion_allowed"] is False
    assert "history_length" in payload["failed_gates"]
    assert "point_in_time_financials" in payload["failed_gates"]
    assert payload["safety"]["auto_code_deletion"] is False


def test_auto_iteration_allows_shadow_only_after_every_gate_passes(tmp_path):
    _write(tmp_path, "quality/latest.json", {
        "total": 3,
        "summary": {"ok": 3},
        "stocks": [{"rows": 1300}],
    })
    _write(tmp_path, "universe/stocks.json", {"count": 2500, "stocks": [{}] * 2500})
    _write(tmp_path, "interim_reports/index.json", {"status": "partial"})
    items = [{
        "20d": {
            "sample_count": 120,
            "hit_rate": 0.60,
            "avg_signed_return_pct": 1.0,
            "max_adverse_pct": -10,
        },
    }] * 10
    _write(tmp_path, "strategy_backtest/index.json", {"items": items})

    payload = build_iteration_status(tmp_path, tmp_path)

    assert payload["phase"] == "shadow_candidate"
    assert payload["strategy_status"] == "eligible_for_shadow"
    assert payload["promotion_allowed"] is True
    assert payload["failed_gates"] == []
