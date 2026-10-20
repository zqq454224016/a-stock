from quant_system.strategy.regime_router import apply_evidence, classify_regime, etf_signal, route


def _evidence(passed: dict[str, list[str]], active_tracks: dict[str, list[str]]) -> dict:
    regimes = ("rising", "range", "falling", "extreme_risk")
    return {
        "status": "complete",
        "current": {"date": "2026-10-19", "regime": "range"},
        "tracks": {
            track: {"by_regime": {r: {"active": r in active_tracks.get(track, [])} for r in regimes}}
            for track in ("long", "short_3_5", "ultra_1_2", "defensive_reversal")
        },
        "strategies": {
            name: {"by_regime": {r: {"evidence_passed": r in rs} for r in regimes}}
            for name, rs in passed.items()
        },
    }


def test_evidence_blocks_table_enabled_routes_without_edge_and_reads_reversal_setup():
    context = {"regime": "震荡", "index_avg_change_pct": 0.1, "trade_date": "2026-10-19",
               "sentiment": {"breadth": 0.1}}
    routed = route(context)
    assert routed["state"] == "range"
    evidence = _evidence({"rev_oversold_hs300_h3": ["range"]}, {"long": ["rising"]})
    evidence["current"]["reversal_setups"] = {"510300": {"date": "2026-10-19", "met": 3, "passed": True}}
    result = apply_evidence(routed, evidence, context)
    assert result["evidence"]["regime"] == "range"
    assert "short_3_5" not in result["evidence_enabled"]
    assert any(item["route"] == "short_3_5" for item in result["blocked_by_evidence"])
    setup = result["reversal_setups"][0]
    assert setup["etf"] == "510300" and setup["setup_passed"] is True and setup["conditions_met"] == 3
    assert result["evidence_cash_floor"] == routed["cash_floor"]


def test_evidence_missing_keeps_router_observational():
    routed = route({"regime": "偏强", "index_avg_change_pct": 1.0})
    result = apply_evidence(routed, None, {})
    assert result["evidence"]["status"] == "missing"
    assert result["evidence_enabled"] == []


def test_regime_router_disables_long_only_tracks_in_downtrend():
    context = {
        "regime": "偏弱",
        "index_avg_change_pct": -1.2,
        "sentiment": {"breadth": -0.3},
    }
    assert classify_regime(context) == "strong_downtrend"
    result = route(context)
    assert "defensive_etf" in result["enabled"]
    assert "short_3_5" in result["disabled"]
    assert result["cash_floor"] >= 0.8


def test_inverse_etf_requires_product_trend_and_downtrend():
    row = {"close": 10, "ma20": 9.5, "ma60": 9, "volume_ratio": 1.2}
    assert etf_signal(row, state="strong_downtrend", product_type="inverse")["passed"]
    assert not etf_signal(row, state="range", product_type="inverse")["passed"]


def test_defensive_etf_fails_closed_when_data_missing():
    result = etf_signal({"close": 10}, state="weak_range", product_type="defensive")
    assert result["passed"] is False
    assert result["signal"] == "unavailable"
