from __future__ import annotations

from quant_system.strategy.horizon_analysis import build_horizon_analysis
from quant_system.strategy.horizon_tracks import TRACK_LONG, TRACK_SHORT, track_for_horizon


def test_track_mapping_separates_short_and_long() -> None:
    assert track_for_horizon("short") == TRACK_SHORT
    assert track_for_horizon("medium") == TRACK_LONG
    assert track_for_horizon("long") == TRACK_LONG


def test_horizon_analysis_does_not_let_swing_champion_speak_for_short_or_long() -> None:
    payload = build_horizon_analysis(
        strategy_iteration={
            "run_id": "test",
            "research_version": "15.x",
            "selected_candidate": "tf_pullback_rising_regime",
            "selected_horizon": "swing",
            "promotion_passed": False,
            "decision": "research_diagnostic_wait_forward_shadow",
            "horizon_results": {
                "short": {
                    "selected_candidate": "baseline_short",
                    "baseline_candidate": "baseline_short",
                    "promotion_passed": False,
                    "selected_oos": {"avg_net_return_pct": -0.2, "hit_rate": 0.4, "trades": 10, "portfolio": {}},
                    "baseline_oos": {},
                },
                "long": {
                    "selected_candidate": "long_quality_trend_gate",
                    "baseline_candidate": "baseline_long",
                    "promotion_passed": False,
                    "selected_oos": {"avg_net_return_pct": 0.0, "hit_rate": 0.0, "trades": 0, "portfolio": {}},
                    "baseline_oos": {},
                },
                "swing": {
                    "selected_candidate": "tf_pullback_rising_regime",
                    "baseline_candidate": "baseline_long_only",
                    "promotion_passed": True,
                    "selected_oos": {
                        "avg_net_return_pct": 0.7,
                        "hit_rate": 0.55,
                        "trades": 300,
                        "portfolio": {"accepted_trades": 12, "rejected_capacity": 300, "total_return_pct": -5},
                    },
                    "baseline_oos": {},
                },
            },
            "candidates": [
                {
                    "name": "baseline_short", "horizon": "short", "train_score": 1,
                    "train": {}, "oos": {"avg_net_return_pct": -0.2, "hit_rate": 0.4, "trades": 10, "portfolio": {}},
                },
                {
                    "name": "long_quality_trend_gate", "horizon": "long", "train_score": 0,
                    "train": {"trades": 0}, "oos": {"trades": 0, "portfolio": {}},
                },
                {
                    "name": "tf_pullback_rising_regime", "horizon": "swing", "train_score": 9,
                    "train": {}, "oos": {
                        "avg_net_return_pct": 0.7, "hit_rate": 0.55, "trades": 300,
                        "portfolio": {"accepted_trades": 12, "rejected_capacity": 300, "total_return_pct": -5},
                    },
                },
            ],
        },
        overnight_iteration={
            "status": "complete",
            "strategies": {
                "overnight_close_breakout": {"stocks": 10, "trades": 100, "avg_net_return_pct": -0.5},
            },
        },
        recommendation={
            "recommendation_version": "2.2.0",
            "market_context": {"regime": "偏弱"},
            "periods": {"short": {"recommendations": []}, "aggressive": {"recommendations": []}},
            "miss_audit": {
                "anti_chase_exclusion_count": 100,
                "numerical_ready_count": 1,
                "pipeline_intraday_defect": False,
                "examples": [{"code": "600869", "verdict": "design_anti_chase_exclusion"}],
            },
        },
    )

    assert payload["tracks"]["short"]["leader"]["selected_candidate"] == "baseline_short"
    assert payload["tracks"]["long"]["leader"]["selected_candidate"] == "long_quality_trend_gate"
    assert payload["source"]["global_selected_horizon"] == "swing"
    assert payload["tracks"]["short"]["analysis"]["verdict"] == "short_track_strategy_or_design_hold"
    assert payload["tracks"]["long"]["analysis"]["verdict"] == "long_track_not_ready"
    assert payload["comparison"]["short_verdict"] != payload["source"]["global_selected_horizon"]
