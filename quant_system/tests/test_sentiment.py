"""舆情因子单元测试。"""

from quant_system.factors.sentiment import compute_sentiment_factors


def test_sentiment_bullish():
    raw = {
        "code": "600378",
        "trade_date": "2026-07-02",
        "em_snapshot": {"focus_index": 94.8, "composite_score": 70},
        "em_series": {
            "desire": [
                {"date": "2026-07-01", "参与意愿": 51.0, "参与意愿变化": 1.0},
                {"date": "2026-07-02", "参与意愿": 53.5, "参与意愿变化": 2.5},
            ],
            "focus": [
                {"date": "2026-07-01", "用户关注指数": 94.0},
                {"date": "2026-07-02", "用户关注指数": 95.5},
            ],
        },
        "xueqiu_hot": {"in_hot_tweet": True, "tweet_heat": 100},
        "posts": [{}],
    }
    out = compute_sentiment_factors(raw)
    assert out["label"] == "看多"
    assert out["heat_index"] == 94.8
    assert out["sentiment_accel"] == 1.5
    assert out["long_short_ratio"] is not None


def test_sentiment_neutral_missing():
    raw = {"code": "600378", "trade_date": "2026-07-02", "em_series": {}, "xueqiu_hot": {}}
    out = compute_sentiment_factors(raw)
    assert out["label"] == "中性"
    assert "em_desire_missing" in out["limitations"]
