from __future__ import annotations

from quant_system.recommendation.builder import build_recommendation_payload
from quant_system.tasks.recommendation_job import _load_map
from quant_system.storage.json_store import JsonStore
from quant_system.config.db_config import DBConfig


def _inputs(selector_status: str = "candidate") -> dict:
    code = "600001"
    return {
        "market": {
            "trade_date": "2026-07-09",
            "indices": [{"name": "上证指数", "change_pct": 1.0}],
            "fund_flow": {"main_net": 20},
            "market_distribution": [
                {"label": "涨幅0~5%", "count": 3000},
                {"label": "跌幅0~5%", "count": 1000},
                {"label": "平盘", "count": 100},
            ],
        },
        "stocks": {
            code: {
                "code": code, "name": "测试股份",
                "quality": {"quality_score": 95},
                "analysis": {"returns": {"d5": 5, "d20": 12, "d60": 25}},
            }
        },
        "selectors": {
            code: {
                "upside_score": 88, "status": selector_status,
                "reject_reasons": ["风险门禁未通过"] if selector_status == "rejected" else [],
                "risks": [], "next_triggers": ["跌破20日均线"],
            }
        },
        "predictions": {code: {"direction": "up", "probability": 0.72}},
        "factors": {code: {"factors": {"multi_factor_score": 82, "technical_score": 80}}},
        "impacts": {code: {"impact_score": 20}},
        "enhances": {code: {"fundamentals": {"pe_ttm": 25, "pb": 3}}},
        "replays": {code: {"summary": {"hit_rate": 0.7}}},
    }


def test_build_daily_and_aggressive_recommendation_periods() -> None:
    payload = build_recommendation_payload(**_inputs(), limit=5)

    assert set(payload["periods"]) == {"short", "aggressive", "tail_sector"}
    # 尾盘板块T+1仅为观察周期，回测未过门禁，不得产生正式推荐
    assert all(
        not row.get("formal_recommendation")
        for row in payload["periods"]["tail_sector"].get("recommendations") or []
    )
    assert payload["periods"]["short"]["label"] == "每日筛选推荐"
    assert payload["periods"]["aggressive"]["label"] == "激进板筛选推荐"
    assert not payload["periods"]["short"]["recommendations"]
    assert payload["market_context"]["regime"] == "偏强"
    assert payload["market_context"]["sentiment"]["label"] == "偏热"
    assert payload["market_context"]["sentiment"]["status"] == "valid"


def test_rejected_stock_is_not_forced_into_recommendations() -> None:
    payload = build_recommendation_payload(**_inputs("rejected"), limit=5)

    assert not payload["periods"]["short"]["recommendations"]
    assert payload["periods"]["short"]["shortage_count"] == 5
    assert "不为凑满5只而放宽标准" in payload["periods"]["short"]["shortage_reason"]


def test_additional_permission_boards_are_excluded_from_every_candidate_period() -> None:
    inputs = _inputs()
    source_code = "600001"
    for star_code in ("688001", "689009", "300750", "301001", "920001", "830001", "430001"):
        for field in ("stocks", "selectors", "predictions", "factors", "impacts", "enhances", "replays"):
            inputs[field][star_code] = dict(inputs[field][source_code])
        inputs["stocks"][star_code]["code"] = star_code
        inputs["stocks"][star_code]["name"] = "科创测试"

    payload = build_recommendation_payload(**inputs, limit=5)

    for period in payload["periods"].values():
        all_candidates = period["recommendations"] + period["observation"] + period["evaluated"]
        assert {item["code"] for item in all_candidates} == {source_code}
    assert "additional_permission_boards_excluded_from_all_candidate_periods" in payload["limitations"]


def test_recommendation_loader_skips_incomplete_json(tmp_path) -> None:
    folder = tmp_path / "stocks"
    folder.mkdir()
    (folder / "broken.json").write_text("", encoding="utf-8")
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path

    assert _load_map(store, "stocks") == {}


def test_market_sentiment_uses_full_stock_distribution() -> None:
    inputs = _inputs()
    inputs["market"]["degraded"] = True
    inputs["market"]["market_distribution"] = [{"label": "跌停", "count": 5}]
    template = inputs["stocks"].pop("600001")
    for index in range(120):
        code = f"600{index:03d}"
        inputs["stocks"][code] = {**template, "code": code, "quote": {"change_pct": 2 if index < 90 else -2}}

    payload = build_recommendation_payload(**inputs, limit=5)
    sentiment = payload["market_context"]["sentiment"]

    assert sentiment["status"] == "valid"
    assert sentiment["advancing_count"] == 90
    assert sentiment["declining_count"] == 30
    assert sentiment["label"] == "偏热"


def test_sector_market_enters_context_without_unverified_stock_bonus() -> None:
    inputs = _inputs()
    inputs["market"]["industries"] = [
        {"name": f"行业{i}", "change_pct": 5 - i} for i in range(10)
    ]

    payload = build_recommendation_payload(**inputs, limit=5)
    sector = payload["market_context"]["sector_market"]

    assert sector["status"] == "valid"
    assert sector["leading"][0] == {"name": "行业0", "change_pct": 5.0}
    assert payload["market_context"]["analysis_points"]["sector_market"]["used_in_scoring"] is False
    assert any(
        "市场情绪" in row
        for row in payload["periods"]["short"]["evaluated"][0]["evidence"]
    )


def test_st_name_does_not_add_a_gate_outside_the_requested_filter() -> None:
    inputs = _inputs()
    inputs["stocks"]["600001"]["name"] = "*ST测试"

    payload = build_recommendation_payload(**inputs, limit=5)

    row = payload["periods"]["short"]["evaluated"][0]
    assert "ST或退市风险标的不进入正式推荐" not in row["risks"]


def test_daily_short_recommendation_uses_market_adaptive_filter() -> None:
    inputs = _inputs()
    code = "600001"
    inputs["stocks"][code].update({
        "quote": {"close": 10.0, "change_pct": 4.5},
        "analysis": {
            "returns": {"d5": 5, "d20": 12, "d60": 25},
            "turnover": 6.0,
            "ma": {"ma5": 9.8, "ma10": 9.6, "ma20": 9.4},
        },
        "kline": [{"volume": 100}, {"volume": 120}, {"volume": 150}],
    })
    inputs["enhances"][code]["fundamentals"]["float_cap_yi"] = 100.0
    inputs["daily_snapshots"] = {code: {
        "close": 10.0,
        "change_pct": 4.5,
        "volume_ratio_5d": 1.8,
        "relative_strength_pct": 1.0,
        "intraday_checks": {
            "stock_above_vwap_all_day": True,
            "no_tail_pulse": True,
            "market_above_vwap_all_day": True,
            "market_no_tail_drop": True,
            "late_high_pullback_holds": True,
        },
    }}

    payload = build_recommendation_payload(**inputs, limit=5)
    row = payload["periods"]["short"]["recommendations"][0]

    assert row["daily_filter"]["profile"] == "strong"
    assert row["daily_filter"]["passed"] is True


def test_daily_short_recommendation_fails_closed_when_filter_data_missing() -> None:
    inputs = _inputs()
    inputs["daily_snapshots"] = {"600001": {"change_pct": 4.5}}

    payload = build_recommendation_payload(**inputs, limit=5)
    row = payload["periods"]["short"]["evaluated"][0]

    assert not payload["periods"]["short"]["recommendations"]
    assert row["daily_filter"]["passed"] is False
    assert any("缺少流通市值" in risk for risk in row["risks"])


def test_aggressive_board_recommends_strong_market_breakout_with_risk_control() -> None:
    inputs = _inputs()
    code = "600001"
    bars = [
        {"close": 8.0 + index * 0.02, "high": 8.1 + index * 0.02, "volume": 100.0}
        for index in range(61)
    ]
    bars[-3]["volume"], bars[-2]["volume"], bars[-1]["volume"] = 100.0, 150.0, 220.0
    inputs["stocks"][code].update({
        "quote": {"close": 10.0, "change_pct": 6.0},
        "analysis": {
            "returns": {"d5": 8, "d20": 15, "d60": 30},
            "turnover": 12.0,
            "ma": {"ma5": 9.7, "ma10": 9.4, "ma20": 9.0},
        },
        "kline": bars,
    })
    inputs["enhances"][code]["fundamentals"]["float_cap_yi"] = 100.0
    inputs["daily_snapshots"] = {code: {
        "close": 10.0,
        "change_pct": 6.0,
        "turnover_pct": 12.0,
        "volume_ratio_5d": 2.2,
        "relative_strength_pct": 2.0,
        "intraday_checks": {
            "stock_above_vwap_all_day": True,
            "no_tail_pulse": True,
            "market_above_vwap_all_day": True,
            "market_no_tail_drop": True,
        },
    }}

    row = build_recommendation_payload(**inputs, limit=5)["periods"]["aggressive"]["recommendations"][0]

    assert row["daily_filter"]["profile"] == "aggressive"
    assert row["risk_control"]["stop_loss_pct"] == -4.0
    assert row["risk_control"]["max_holding_days"] == 5


def test_aggressive_board_closes_when_market_is_not_strong() -> None:
    inputs = _inputs()
    inputs["market"]["indices"] = [{"name": "上证指数", "change_pct": -1.0}]
    inputs["market"]["fund_flow"] = {"main_net": -120}

    payload = build_recommendation_payload(**inputs, limit=5)

    assert not payload["periods"]["aggressive"]["recommendations"]
    assert any(
        "仅在偏强市场开放" in risk
        for risk in payload["periods"]["aggressive"]["evaluated"][0]["risks"]
    )


def test_miss_audit_marks_same_day_large_gainer_as_anti_chase() -> None:
    inputs = _inputs()
    inputs["market"]["indices"] = [{"name": "上证指数", "change_pct": -1.0}]
    inputs["market"]["fund_flow"] = {"main_net": -120}
    code = "600869"
    template = inputs["stocks"].pop("600001")
    for field in ("selectors", "predictions", "factors", "impacts", "enhances", "replays"):
        inputs[field][code] = inputs[field].pop("600001")
    inputs["stocks"][code] = {
        **template,
        "code": code,
        "name": "远东股份",
        "quote": {"close": 19.24, "change_pct": 6.42},
        "analysis": {
            "returns": {"d5": 12, "d20": 5, "d60": 8},
            "turnover": 11.6,
            "ma": {"ma5": 17.39, "ma10": 17.49, "ma20": 19.85},
        },
        "kline": [{"volume": 100}, {"volume": 120}, {"volume": 150}],
    }
    inputs["enhances"][code]["fundamentals"]["float_cap_yi"] = 427.0
    inputs["daily_snapshots"] = {code: {
        "close": 19.24,
        "change_pct": 6.42,
        "turnover_pct": 11.6,
        "float_cap_yi": 427.0,
        "volume_ratio_5d": 1.85,
        "relative_strength_pct": 6.33,
    }}

    payload = build_recommendation_payload(**inputs, limit=5)
    row = payload["periods"]["short"]["evaluated"][0]
    miss = payload["miss_audit"]

    assert row["daily_filter"]["exclusion"]["design_anti_chase"] is True
    assert row["daily_filter"]["numerical_passed"] is False
    assert miss["examples"][0]["code"] == "600869"
    assert miss["examples"][0]["verdict"] == "design_anti_chase_exclusion"
    assert miss["promotion_alignment"]["same_day_chase_is_not_promotion_target"] is True
