"""P1-3 数据增强单元测试。"""

from quant_system.pipeline.enhance_builder import build_enhance_payload, summarize_enhance


def test_build_enhance_payload():
    payload = build_enhance_payload(
        "600378",
        "昊华科技",
        valuation={
            "source": "eastmoney_value",
            "trade_date": "2026-07-03",
            "pe_ttm": 45.2,
            "pb": 3.1,
            "market_cap_yi": 980.5,
        },
        dividends=[{"announce_date": "2026-06-05", "cash_div": 3.92, "ex_date": "2026-06-12"}],
        lockups=[{"unlock_date": "2028-01-10", "pct_total": 0.0156}],
        forecast={"forecast_type": "预增", "change_pct": 12.5},
        northbound={
            "trade_date": "2026-07-03",
            "hold_pct": 2.35,
            "net_buy_amount_yi": 0.12,
            "hold_value_yi": 23.0,
        },
        margin={"margin_balance_yi": 1.2, "source": "sse"},
        market={
            "trade_date": "2026-07-03",
            "indices": [{"name": "上证指数", "code": "000001", "close": 4028.9, "change_pct": -2.03}],
            "fund_flow": {"north_net": -15.2, "main_net": -80.5},
        },
        stock_analysis={"analysis": {"returns": {"d20": 89.81}}},
        quality={
            "status": "ok",
            "quality_score": 95,
            "cross_source_diff": {
                "status": "pass",
                "primary_source": "eastmoney",
                "compare_source": "sina",
                "close_diff_pct": 0.012,
            },
        },
        sources_failed=["individual_info"],
    )
    assert payload["code"] == "600378"
    assert payload["fundamentals"]["pe_ttm"] == 45.2
    assert payload["corporate"]["dividends"][0]["cash_div"] == 3.92
    assert payload["fund_flow"]["northbound"]["hold_pct"] == 2.35
    assert payload["index_context"]["stock_return_20d"] == 89.81
    assert payload["cross_source"]["status"] == "pass"
    assert "partial_source_failure" in payload["limitations"]

    summary = summarize_enhance(payload)
    assert summary["pe_ttm"] == 45.2
    assert summary["north_hold_pct"] == 2.35
    assert summary["next_lockup"] == "2028-01-10"


def test_enhance_missing_sources():
    payload = build_enhance_payload(
        "000001",
        "平安银行",
        valuation={},
        dividends=[],
        lockups=[],
        forecast=None,
        northbound={},
        margin=None,
        market=None,
        stock_analysis=None,
        quality=None,
        sources_failed=["valuation_em", "northbound"],
    )
    assert "valuation_missing" in payload["limitations"]
    assert "northbound_missing" in payload["limitations"]
    assert "dividend_missing" in payload["limitations"]
