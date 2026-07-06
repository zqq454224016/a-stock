"""基本面/资金因子单元测试。"""

from quant_system.factors.fundamental import compute_enhance_factors, score_fundamental, score_fund_flow


def _sample_enhance():
    return {
        "trade_date": "2026-07-03",
        "fundamentals": {
            "source": "eastmoney_value",
            "pe_ttm": 25.0,
            "pb": 2.5,
            "market_cap_yi": 980.0,
        },
        "corporate": {
            "lockups": [{"unlock_date": "2028-01-10", "pct_float": 0.02}],
            "earnings_forecast": {"forecast_type": "预增", "change_pct": 30.0},
        },
        "fund_flow": {
            "northbound": {
                "hold_pct": 2.5,
                "net_buy_amount_yi": 0.15,
            },
            "margin": {
                "margin_balance_yi": 10.0,
                "margin_buy_yi": 2.0,
            },
        },
    }


def test_fundamental_score_value():
    score, detail = score_fundamental(_sample_enhance())
    assert score is not None
    assert score > 50
    assert detail["pe_ttm"] == 25.0


def test_fund_flow_score():
    score, detail = score_fund_flow(_sample_enhance())
    assert score is not None
    assert score > 50
    assert detail["has_northbound"] is True


def test_compute_enhance_factors_missing():
    out = compute_enhance_factors(None)
    assert out["fundamental_score"] is None
    assert "fundamental_missing" in out["limitations"]
