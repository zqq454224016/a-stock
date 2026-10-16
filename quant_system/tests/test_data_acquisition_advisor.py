import json

from quant_system.ai.data_acquisition_advisor import evidence_fingerprint
from quant_system.ai.prompts.data_acquisition import (
    PLANNER_PROMPT,
    PROMPT_VERSION,
    build_planner_prompt,
    extract_json_object,
    normalize_plan,
    score_plan,
    validate_plan,
)


def test_ai_advisor_scope_excludes_strategy_changes():
    assert "唯一目标" in PLANNER_PROMPT
    assert "修改或建议修改策略参数" in PLANNER_PROMPT
    assert "data_acquisition_methods_only" in PLANNER_PROMPT


def test_acquisition_fingerprint_is_stable():
    assert evidence_fingerprint({"b": 2, "a": 1}) == evidence_fingerprint({"a": 1, "b": 2})


def _valid_plan():
    return {
        "prompt_version": PROMPT_VERSION,
        "scope": "data_acquisition_methods_only",
        "summary": "补齐历史行情和点时财务。",
        "gaps": [{
            "id": "D001",
            "priority": "P0",
            "dataset": "历史日线",
            "status": "actionable",
            "evidence_paths": ["iteration.data.max_history_bars"],
            "required_fields": ["symbol", "trade_date", "close"],
            "primary_sources": [{
                "name": "TickFlow", "authority": "licensed",
                "access": "configured", "capability": "批量日线能力待验证",
            }],
            "time_semantics": ["as_of", "published_at", "known_at", "fetched_at"],
            "incremental_plan": {
                "initial_backfill": "按年度分块",
                "cursor": "trade_date",
                "frequency": "每日",
                "rate_limit": "按配置限流",
                "cache": "保存原始日快照",
            },
            "quality_checks": ["OHLC 合法"],
            "fallback": ["失败时保留上一快照并标记 stale"],
            "permission_action": "核对已购套餐权限",
            "implementation_steps": ["验证接口", "小样本回填"],
            "acceptance": ["至少 1250 根且无重复日期"],
            "risks": ["复权口径待核对"],
        }],
        "execution_order": ["D001"],
        "global_quality_rules": ["禁止未来数据"],
        "next_round_inputs": ["回填覆盖率"],
        "strategy_changes": [],
        "trading_actions": [],
        "unknowns": ["接口历史深度待验证"],
    }


def test_valid_plan_scores_100():
    payload = _valid_plan()
    evaluation = score_plan(payload)
    assert validate_plan(payload) == []
    assert evaluation["passed"] is True
    assert evaluation["score"] == 100


def test_normalize_plan_repairs_only_required_time_semantics():
    payload = _valid_plan()
    payload["gaps"][0]["time_semantics"] = ["as_of", "known_at", "fetched_at", "effective_from"]
    repairs = normalize_plan(payload)
    assert repairs == ["gaps[0].time_semantics 补齐: published_at"]
    assert payload["gaps"][0]["time_semantics"] == [
        "as_of", "known_at", "fetched_at", "effective_from", "published_at",
    ]
    assert validate_plan(payload) == []


def test_prompt_rejects_strategy_or_trading_scope():
    payload = _valid_plan()
    payload["strategy_changes"] = ["调整策略参数提高命中率"]
    payload["trading_actions"] = ["买入"]
    errors = validate_plan(payload)
    assert any("strategy_changes" in error for error in errors)
    assert any("trading_actions" in error for error in errors)
    assert score_plan(payload, errors)["passed"] is False


def test_extract_json_and_prompt_do_not_include_credentials():
    payload = _valid_plan()
    content = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    assert extract_json_object(content)["scope"] == "data_acquisition_methods_only"
    prompt = build_planner_prompt({"configured_sources": {"tickflow": True}})
    assert "secret-value" not in prompt
    assert '"tickflow":true' in prompt
