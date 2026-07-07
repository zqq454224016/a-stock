"""历史视角滚动推演测试。"""

import pandas as pd

from quant_system.replay.walk_forward import build_replay_payload


def _df(n: int = 80) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "open": [10 + i * 0.1 for i in range(n)],
        "high": [10.5 + i * 0.1 for i in range(n)],
        "low": [9.8 + i * 0.1 for i in range(n)],
        "close": [10.2 + i * 0.1 for i in range(n)],
        "volume": [100000 + i * 1000 for i in range(n)],
        "amount": [1000000 + i * 10000 for i in range(n)],
    })


def test_replay_uses_previous_day_as_knowledge_cutoff():
    payload = build_replay_payload("600001", "测试", _df(), days=10)

    assert payload["status"] == "ok"
    assert payload["replay_version"] == "1.1.0"
    assert len(payload["steps"]) == 10
    for step in payload["steps"]:
        assert step["knowledge_cutoff"] < step["target_date"]
        assert step["actual"]["return_pct"] is not None
        assert "root_cause" in step
        assert "actual_root_causes" in step["root_cause"]
        assert "model_iteration_notes" in step["root_cause"]
        assert "operation_levels" in step
        assert step["operation_levels"]["buy_trigger_price"] > 0
    assert payload["learning"]["hit_rate_improvement_thoughts"]
    assert "root_cause_distribution" in payload["learning"]


def test_replay_marks_insufficient_history():
    payload = build_replay_payload("600001", "测试", _df(20), days=10)

    assert payload["status"] == "insufficient_data"
    assert payload["steps"] == []


def test_replay_adds_market_fundamental_and_impact_root_causes():
    context = {
        "market": {
            "trade_date": "2026-01-15",
            "indices": [{"name": "上证指数", "change_pct": -1.6}],
            "fund_flow": {"main_net": -260.0, "north_net": -45.0},
            "market_distribution": [
                {"label": "涨幅0~5%", "count": 600},
                {"label": "跌幅0~5%", "count": 1800},
            ],
        },
        "enhance": {
            "trade_date": "2026-01-15",
            "fundamentals": {"pe_ttm": 88, "pb": 11},
            "corporate": {"earnings_forecast": {"announce_date": "2026-01-10", "change_pct": 45}},
            "fund_flow": {"northbound": {"net_buy_amount_yi": -0.8}},
        },
        "impact": {
            "trade_date": "2026-01-15",
            "events": [
                {
                    "event_type": "material_or_product_price",
                    "title": "产品价格维持高位",
                    "announce_date": "2026-01-10",
                    "impact_score": 30,
                    "impact_direction": "positive",
                    "evidence": ["产品价格维持高位"],
                }
            ],
        },
    }
    payload = build_replay_payload("600001", "测试", _df(), days=3, context=context)

    causes = payload["steps"][0]["root_cause"]["external_context_causes"]
    labels = {c["label"] for c in causes}
    assert "上证指数 走弱" in labels
    assert "市场主力资金净流出" in labels
    assert "估值压力偏高" in labels
    assert "业绩预告增长" in labels
    assert "产品价格维持高位" in labels
    assert {c["source_timing"] for c in causes} == {"known_at_cutoff"}
