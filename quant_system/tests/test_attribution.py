from __future__ import annotations

from quant_system.attribution import build_daily_attribution_payload


def _stock() -> dict:
    rows = []
    closes = [10, 10.2, 10.4, 10.6, 10.8, 11.0, 11.2, 11.1, 11.6, 10.7]
    for i, close in enumerate(closes, start=1):
        rows.append({
            "date": f"2026-07-{i:02d}",
            "open": close - 0.2,
            "high": close + 0.4,
            "low": close - 0.5,
            "close": close,
            "volume": 1000 + i * 100,
            "ma5": 11.0,
            "ma10": 10.8,
            "ma20": 11.0,
            "ma60": 10.0,
        })
    rows[-2]["volume"] = 2200
    rows[-1]["open"] = 11.7
    rows[-1]["high"] = 12.0
    rows[-1]["low"] = 10.6
    rows[-1]["volume"] = 2600
    return {"code": "600001", "name": "测试", "kline": rows}


def test_daily_attribution_detects_yesterday_up_today_down() -> None:
    payload = build_daily_attribution_payload(
        "600001",
        "测试",
        _stock(),
        market={
            "indices": [{"name": "上证指数", "change_pct": -1.2}],
            "fund_flow": {"main_net": -180},
            "market_distribution": [{"label": "上涨", "count": 1000}, {"label": "下跌", "count": 3000}],
        },
        impact={"impact_direction": "negative", "impact_score": -20},
        replay={
            "steps": [{
                "target_date": "2026-07-10",
                "root_cause": {
                    "actual_root_causes": [{
                        "category": "market_fund",
                        "label": "资金转弱",
                        "effect": "bearish",
                        "evidence": "主力净流出",
                        "source": "market",
                    }]
                },
            }]
        },
    )

    assert payload["status"] == "ok"
    assert payload["pattern"] == "yesterday_up_today_down"
    assert payload["logic_review"]["logic_broken"] is True
    assert payload["summary"]["today_return_pct"] < 0
    today_labels = {x["label"] for x in payload["items"][1]["dominant_causes"]}
    assert "单日跌幅较深" in today_labels
    assert "大盘走弱" in {x["label"] for x in payload["items"][1]["all_causes"]}


def test_daily_attribution_marks_insufficient_data() -> None:
    payload = build_daily_attribution_payload("600001", "测试", {"kline": []})

    assert payload["status"] == "insufficient_data"
    assert payload["limitations"] == ["requires_at_least_3_kline_rows"]
