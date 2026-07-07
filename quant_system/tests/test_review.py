"""后验复盘测试。"""

from quant_system.evaluation.review import build_review_payload


def _stock() -> dict:
    closes = [10, 10.5, 11, 10.8, 11.2, 11.5, 11.8, 11.4, 11.9, 12.2, 12.5, 12.1, 12.6, 12.8, 13.0, 13.2, 13.5, 13.3, 13.8, 14.0, 14.2, 14.5, 14.8]
    return {
        "name": "测试",
        "trade_date": "2026-01-01",
        "kline": [
            {
                "date": f"2026-01-{idx + 1:02d}",
                "open": close,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
            }
            for idx, close in enumerate(closes)
        ],
    }


def test_review_evaluates_prediction_selector_and_decision():
    payload = build_review_payload(
        code="600001",
        name="测试",
        stock=_stock(),
        prediction={"trade_date": "2026-01-01", "direction": "up", "probability": 0.6},
        selector={"trade_date": "2026-01-01", "status": "candidate", "upside_score": 80},
        decision={"trade_date": "2026-01-01", "action": "buy", "position_suggestion": 0.2},
    )

    assert payload["status"] == "ok"
    assert payload["summary"]["evaluated_count"] == 9
    assert payload["summary"]["hit_rate"] == 1.0
    assert payload["sections"]["prediction"]["items"][0]["return_pct"] == 5.0


def test_review_marks_pending_when_future_kline_missing():
    stock = _stock()
    stock["trade_date"] = "2026-01-20"
    payload = build_review_payload(
        code="600001",
        name="测试",
        stock=stock,
        prediction={"trade_date": "2026-01-20", "direction": "up"},
    )

    assert payload["summary"]["evaluated_count"] == 1
    assert payload["summary"]["pending_count"] == 2
    assert payload["sections"]["prediction"]["items"][1]["status"] == "pending"
