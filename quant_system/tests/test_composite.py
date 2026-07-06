"""多因子合成单元测试。"""

from quant_system.factors.composite import build_composite_factors


def test_composite_with_sentiment():
    technical = {
        "ma20_bias": 10,
        "rsi14": 65,
        "macd_hist": 1.0,
        "momentum_20": 10,
        "volume_ratio_20": 1.5,
        "above_ma20": True,
        "ma_cross": "golden",
    }
    sentiment = {
        "desire_score": 53,
        "heat_index": 95,
        "sentiment_accel": 1.5,
        "label": "看多",
        "xueqiu_hot": {"in_hot_tweet": True},
    }
    out = build_composite_factors("600378", "2026-07-02", technical, sentiment=sentiment)
    f = out["factors"]
    assert f["has_sentiment"] is True
    assert f["sentiment_score"] is not None
    assert f["multi_factor_score"] > 0
    assert f["technical_score"] > 0


def test_composite_technical_only():
    technical = {"above_ma20": False, "ma_cross": "death", "rsi14": 35, "macd_hist": -0.5}
    out = build_composite_factors("600378", "2026-07-02", technical)
    f = out["factors"]
    assert f["has_sentiment"] is False
    assert f["sentiment_score"] is None
    assert f["multi_factor_score"] == f["technical_score"]


def test_composite_with_enhance():
    technical = {"above_ma20": True, "ma_cross": "golden", "rsi14": 60, "macd_hist": 0.5}
    enhance = {
        "version": "1.0.0",
        "trade_date": "2026-07-03",
        "fundamentals": {"source": "eastmoney_value", "pe_ttm": 20, "pb": 2.0},
        "corporate": {"lockups": [], "earnings_forecast": None},
        "fund_flow": {
            "northbound": {"hold_pct": 3.0, "net_buy_amount_yi": 0.1},
            "margin": {"margin_balance_yi": 5.0, "margin_buy_yi": 1.0},
        },
    }
    out = build_composite_factors("600378", "2026-07-03", technical, enhance=enhance)
    f = out["factors"]
    assert f["has_fundamental"] is True
    assert f["has_fund_flow"] is True
    assert f["fundamental_score"] is not None
    assert f["fund_flow_score"] is not None
    assert f["multi_factor_score"] != f["technical_score"]
    assert "fundamental" in f["factor_weights"]

