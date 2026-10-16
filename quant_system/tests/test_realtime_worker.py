from datetime import datetime, timedelta

from quant_system.tasks.realtime_worker import build_market_context, build_trade_plan, combine_stock_market, evaluate_kline, notification_decision, state_label
from quant_system.tasks import realtime_worker


def _bars(closes, volumes=None):
    volumes = volumes or [100] * len(closes)
    return [{"close": c, "high": c + .1, "low": c - .1, "volume": v} for c, v in zip(closes, volumes)]


def test_kline_monitor_detects_uptrend_without_position():
    result = evaluate_kline(_bars([10, 10.1, 10.2, 10.3, 10.5, 10.7, 10.9, 11.1, 11.3, 11.6]))
    assert result["state"] in {"uptrend", "strong_uptrend"}
    assert result["confidence"] >= 50
    assert "support" in result and "resistance" in result


def test_kline_monitor_detects_downtrend_and_insufficient_data():
    result = evaluate_kline(_bars([11.6, 11.4, 11.2, 11, 10.8, 10.6, 10.4, 10.2, 10, 9.8]))
    assert result["state"] in {"downtrend", "strong_downtrend"}
    assert evaluate_kline(_bars([10, 10.1]))["state"] == "insufficient_data"


def test_unavailable_realtime_never_uses_reference_price_or_notifies(monkeypatch, tmp_path):
    monkeypatch.setattr(realtime_worker, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(realtime_worker, "fetch_minute", lambda *args, **kwargs: __import__("pandas").DataFrame())
    monkeypatch.setattr(realtime_worker, "_five_minute_fallback", lambda *args, **kwargs: [])
    called = []
    monkeypatch.setattr(realtime_worker, "notify_realtime_advice", lambda *args, **kwargs: called.append(True))
    result = realtime_worker.run_once({"code": "600206", "reference_close": 50.21})
    assert result["latest"]["close"] == 0
    assert result["feishu"]["reason"] == "realtime_kline_unavailable"
    assert not called


def test_realtime_push_rejects_non_single_stock_scope():
    try:
        realtime_worker.run_once({"push_scope": "portfolio", "code": "600206"})
    except ValueError as exc:
        assert "单只股票" in str(exc)
    else:
        raise AssertionError("non-single-stock push scope must be rejected")


def test_notification_requires_distinct_bars_and_applies_cooldown():
    advice = {"state": "strong_uptrend", "confidence": 85, "support": 10, "resistance": 11}
    now = datetime(2026, 8, 19, 10, 0)
    config = {"notification_confirm_bars": 2, "notification_cooldown_minutes": 60}
    send, reason, state = notification_decision(advice, 11, {}, now, config, bar_id="09:55")
    assert not send and reason == "awaiting_distinct_bar_confirmation"
    send, reason, state = notification_decision(advice, 11, state, now, config, bar_id="09:55")
    assert not send and reason == "awaiting_distinct_bar_confirmation"
    send, reason, state = notification_decision(advice, 11, state, now, config, bar_id="10:00")
    assert send and reason == "首次形成可执行趋势"
    send, reason, state = notification_decision(advice, 11.3, state, now + timedelta(minutes=5), config, bar_id="10:05")
    assert not send and reason == "cooldown_active"


def test_notification_silences_range_and_honors_daily_limit():
    now = datetime(2026, 8, 19, 14, 0)
    send, reason, _ = notification_decision(
        {"state": "range", "confidence": 85}, 10, {}, now, {}, bar_id="14:00"
    )
    assert not send and reason == "non_actionable_state"
    old = {"date": "2026-08-19", "daily_count": 3, "pending_state": "strong_downtrend", "pending_count": 2}
    send, reason, _ = notification_decision(
        {"state": "strong_downtrend", "confidence": 85, "support": 9, "resistance": 10},
        8.9, old, now, {"notification_daily_limit": 3}, bar_id="14:00",
    )
    assert not send and reason == "daily_limit_reached"


def test_market_context_adds_relative_strength():
    class FakeAPI:
        def fetch_tencent_quotes(self, _codes):
            return [
                {"code": "000001", "change_pct": 0.2},
                {"code": "399001", "change_pct": -0.2},
                {"code": "600206", "change_pct": 1.5},
            ]
    rows = [
        {"date": "2026-08-20 15:00", "close": 50},
        {"date": "2026-08-21 10:00", "close": 51},
    ]
    result = build_market_context(rows, FakeAPI())
    assert result["regime"] == "市场震荡"
    assert result["stock_change_pct"] == 2.0
    assert result["relative_label"] == "强于大盘"


def test_market_context_falls_back_to_stock_snapshot_change():
    class FakeAPI:
        def fetch_tencent_quotes(self, _codes):
            return [
                {"code": "000001", "change_pct": -0.2},
                {"code": "399001", "change_pct": -0.8},
                {"code": "600206", "change_pct": -3.24},
            ]
    rows = [{"date": "2026-08-25 11:30", "close": 50.82}]
    result = build_market_context(rows, FakeAPI(), code="600206")
    assert result["stock_change_pct"] == -3.24
    assert result["relative_strength_pct"] == -2.74
    assert result["relative_label"] == "弱于大盘"


def test_combined_analysis_distinguishes_resonance_and_weak_countertrend_bounce():
    advice = {"trend": "强势上行", "score": 5, "confidence": 85, "features": {"volume_ratio": 1.3}}
    strong_market = {"status": "available", "index_average_change_pct": 0.8, "relative_strength_pct": 1.0}
    assert combine_stock_market(advice, strong_market)["relation"] == "顺势共振"
    weak_market = {"status": "available", "index_average_change_pct": -0.8, "relative_strength_pct": 0.3}
    result = combine_stock_market({**advice, "features": {"volume_ratio": 0.4}}, weak_market)
    assert result["conclusion"] == "个股反弹但受大盘压制"
    assert result["confidence"] == 70


def test_combined_analysis_flags_stock_specific_weakness():
    advice = {"trend": "弱势下行", "score": -4, "confidence": 78, "features": {"volume_ratio": 1.0}}
    market = {"status": "available", "index_average_change_pct": 0.6, "relative_strength_pct": -2.0}
    assert combine_stock_market(advice, market)["relation"] == "显著弱于大盘"


def test_trade_plan_gives_explicit_buy_sell_and_targets():
    advice = {"score": 4, "confidence": 78, "support": 10, "resistance": 10.5,
              "features": {"average_range": 0.2}}
    plan = build_trade_plan(advice, {"confidence": 83, "relation": "顺势共振"}, 10.4)
    assert plan["bias"] == "进攻"
    assert plan["breakout_buy"] > 10.5
    assert plan["stop_loss"] < 10
    assert plan["target_2"] > plan["target_1"]


def test_trade_plan_weak_signal_explicitly_sells_instead_of_holds():
    advice = {"score": -4, "confidence": 78, "support": 9.8, "resistance": 10.4,
              "features": {"average_range": 0.2}}
    plan = build_trade_plan(advice, {"confidence": 83, "relation": "弱势共振"}, 10)
    assert plan["bias"] == "防守"
    assert "卖出" in plan["action"]
    assert plan["sell_trigger"] < 9.8


def test_state_labels_and_transition_reason_are_chinese():
    assert state_label("strong_downtrend") == "弱势下行"
    now = datetime(2026, 8, 25, 10, 0)
    old = {"date": "2026-08-25", "pending_state": "strong_uptrend", "pending_count": 2,
           "last_notified_state": "downtrend", "last_notified_at": "2026-08-25T08:00:00",
           "last_notified_price": 10, "daily_count": 1}
    advice = {"state": "strong_uptrend", "confidence": 85, "support": 10, "resistance": 11}
    send, reason, _ = notification_decision(advice, 11, old, now, {}, bar_id="10:00")
    assert send
    assert reason == "趋势由震荡偏弱切换为强势上行"
    assert "downtrend" not in reason
