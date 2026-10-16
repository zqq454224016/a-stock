"""Evidence-based readiness audit for recommendation-only operation (no broker)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.iteration.authority_policy import authority_policy
from quant_system.trading import execution_simulator, order_state, portfolio_risk
from quant_system.utils.time_utils import now_str

FINAL_SYSTEM_OBJECTIVE = {
    "id": "recommendation_strategy_only",
    "description": (
        "推荐策略系统：全市场选股后输出带证据、风险检查和失效条件的推荐与操作区间；"
        "本地纸面执行模拟仅用于校验可成交约束，不连接券商、不自动报单"
    ),
    "operating_modes": [
        "recommendation_only",
        "paper_observation",
    ],
    "abandoned_modes": [
        "broker_automated_execution",
    ],
    "instruction_contract": [
        "symbol",
        "as_of",
        "action",
        "target_quantity_or_weight",
        "order_type",
        "limit_price_or_trigger",
        "valid_until",
        "strategy_version",
        "risk_checks",
        "invalidation_reason",
    ],
    "execution_policy": {
        "broker_integration": False,
        "auto_order_submission": False,
        "paper_simulation_allowed": True,
        "human_decides_real_trades": True,
    },
}

VALIDATION_PROTOCOL = {
    "id": "t_minus_60_research_and_forward_60_validation",
    "research_window": {
        "range": "<= T-60 trading days",
        "purpose": "并发训练、滚动回归、多方向假设开发与淘汰",
        "parallel_allowed": True,
        "promotion_allowed": False,
    },
    "recent_history_window": {
        "range": "(T-60, T]",
        "purpose": "已被观察的污染诊断区，仅用于数据与执行异常诊断",
        "model_selection_allowed": False,
        "parameter_tuning_allowed": False,
        "promotion_allowed": False,
    },
    "forward_shadow_window": {
        "range": "策略冻结后的未来至少60个交易日",
        "signals_immutable": True,
        "evaluation_count": 1,
        "promotion_allowed_after_minimum_days": True,
    },
    "parallel_research_rules": [
        "每个方向预登记假设、特征、参数、持有期、费用和淘汰标准",
        "研究方向不得读取最近60日诊断结果或前向结果来调参",
        "记录全部试验并执行多重比较控制",
        "并发只提高计算吞吐量，不改变验证门槛",
    ],
}

ABANDONED_SCOPE = [
    {
        "name": "broker_order_gateway",
        "reason": "当前方案只做推荐策略，不接入券商程序化交易接口",
    },
    {
        "name": "operations_and_compliance_for_live_trading",
        "reason": "真实下单运维合规随自动交易一并放弃；推荐与纸面模拟仍保留本地审计",
    },
]


def _research_version_at_least(payload: dict[str, Any], major: int) -> bool:
    try:
        return int(str(payload.get("research_version") or "0").split(".", 1)[0]) >= major
    except (TypeError, ValueError):
        return False


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_trading_readiness_audit(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    data = cfg.data_dir
    public_supplement = _read(data / "public_supplement/status.json")
    public_sets = public_supplement.get("datasets") or {}
    robust = _read(data / "strategy_iterations/latest.json")
    regime = _read(data / "market_regime/status.json")
    market_events = _read(data / "market_events/status.json")
    execution = _read(data / "execution_history/status.json")
    financial_backfill = _read(data / "point_in_time_financials/backfill_status.json")
    realtime_quotes = _read(data / "normalized/market.quotes.tencent/latest.json")
    trade_plans = _read(data / "trade_plans/summary.json")
    forward_shadow = _read(data / "forward_shadow/status.json")
    candidate_financials = public_sets.get("candidate_financials") or {}

    forward_promoted = (
        forward_shadow.get("status") == "evaluated"
        and bool(forward_shadow.get("promotion_passed"))
        and str(forward_shadow.get("decision") or "") == "promote_from_forward_shadow"
    )
    instruction_ready = (
        trade_plans.get("status") in {"recommendation_ready", "paper_observation"}
        and trade_plans.get("instruction_contract_version") is not None
    )

    checks = [
        ("five_year_prices", bool(robust.get("usable_stocks", 0) >= 2000), "TickFlow", "全市场五年日线"),
        ("purged_oos_validation", _research_version_at_least(robust, 3), "local", "冻结候选、隔离期、成本后样本外"),
        (
            "stable_promoted_strategy",
            bool(robust.get("promotion_passed")) or forward_promoted,
            "local forward_shadow evaluation" if forward_promoted else "local",
            "当前没有跨时段稳定晋级策略" if not (robust.get("promotion_passed") or forward_promoted)
            else "前向影子满窗评估已通过，推荐正式启用仍需人工确认",
        ),
        ("historical_trade_status_full_market", market_events.get("status") == "complete", "Python交易日历差集+深交所简称变更+上交所官方公告PDF", "历史ST变更、被删除停牌日和除权日可成交状态"),
        (
            "point_in_time_financial_summary",
            financial_backfill.get("status") == "complete" and int(financial_backfill.get("period_count") or 0) >= 20,
            "东方财富公开季度批量表；Python公告日约束与未来记录隔离",
            "普通沪深主板五年季度摘要、published_at、known_at和不可变版本",
        ),
        (
            "candidate_full_financials_verified",
            candidate_financials.get("status") == "available"
            and int(candidate_financials.get("complete") or 0) >= int(candidate_financials.get("requested") or 1),
            "Python公开源补完整三表；交易所/巨潮核验公告时间",
            "最终候选完整三表、published_at、known_at、修订版本和跨源核验",
        ),
        ("announcements_point_in_time", market_events.get("status") == "complete", "交易所公告索引、PDF规则解析与AI异常版式提取", "公告唯一ID、发布时间、类别、正文/PDF"),
        ("historical_market_regime", bool(regime.get("days", 0) >= 1000), "TickFlow本地聚合；仍缺涨跌停/炸板历史", "五年指数、市场宽度、成交额、涨跌停/炸板历史"),
        ("corporate_actions_adjustment", execution.get("status") == "complete" and int(execution.get("corporate_action_events_inferred") or 0) > 0, "TickFlow原始/前复权双价格推导+公开公司行为", "全市场分红送转、除权除息与可复现复权"),
        (
            "portfolio_execution_v1",
            _research_version_at_least(robust, 9)
            and str((robust.get("method") or {}).get("portfolio") or "").startswith("cash_constrained_"),
            "deterministic Python",
            "现金约束、仓位限制、容量拒单、确定性候选排序和逐日资金曲线",
        ),
        (
            "execution_simulator",
            execution_simulator.is_ready(),
            f"local paper simulator {execution_simulator.capabilities()['version']}",
            "T+1、涨跌停、停牌、滑点、部分成交、费用（仅纸面，无券商）",
        ),
        (
            "portfolio_risk_engine",
            portfolio_risk.is_ready(),
            f"local paper risk {portfolio_risk.capabilities()['version']}",
            "仓位、行业集中度、回撤和熔断告警（推荐纸面账户）",
        ),
        (
            "realtime_market_feed",
            realtime_quotes.get("status") == "available" and bool(realtime_quotes.get("items")),
            "腾讯公开行情",
            "带服务端时间、交易状态和新鲜度门禁的实时行情",
        ),
        (
            "recommendation_instruction_engine",
            instruction_ready,
            "deterministic Python trade_plans",
            "选股后输出推荐动作、价格区间、有效期、风险检查与失效条件（不报单）",
        ),
        (
            "order_state_machine",
            bool(order_state.capabilities()["states"]) and order_state.capabilities()["broker_integration"] is False,
            f"local paper orders {order_state.capabilities()['version']}",
            "待报、部成、全成、拒单与幂等（仅纸面模拟）",
        ),
        (
            "paper_trading_observation",
            forward_shadow.get("status") in {"evaluation_due", "evaluated"}
            and int(forward_shadow.get("recorded_trading_days") or 0) >= 60
            and bool(forward_shadow.get("overwrite_forbidden")),
            "不可覆盖的本地前向影子账本",
            "策略冻结后至少60个交易日真实行情窗口；满窗只评估一次",
        ),
    ]
    categories = {
        "five_year_prices": "data",
        "historical_trade_status_full_market": "data",
        "point_in_time_financial_summary": "data",
        "candidate_full_financials_verified": "data",
        "announcements_point_in_time": "data",
        "historical_market_regime": "data",
        "corporate_actions_adjustment": "data",
        "realtime_market_feed": "data",
        "purged_oos_validation": "research_evidence",
        "stable_promoted_strategy": "research_evidence",
        "paper_trading_observation": "research_evidence",
        "portfolio_execution_v1": "execution",
        "execution_simulator": "execution",
        "portfolio_risk_engine": "execution",
        "recommendation_instruction_engine": "execution",
        "order_state_machine": "execution",
    }
    items = [
        {
            "name": name, "ready": ready, "provider": provider,
            "requirement": requirement, "category": categories[name],
        }
        for name, ready, provider, requirement in checks
    ]
    missing = [item for item in items if not item["ready"]]
    # Recommendation product can be ready for research output without stable promotion;
    # formal recommendation activation still lists stable strategy as evidence.
    research_blocking = {
        item["name"] for item in missing if item["category"] == "research_evidence"
    }
    execution_blocking = {
        item["name"] for item in missing if item["category"] == "execution"
    }
    if not missing:
        status = "recommendation_ready"
    elif not execution_blocking and research_blocking <= {"stable_promoted_strategy"}:
        status = "recommendation_pipeline_ready"
    else:
        status = "research_only"

    payload = {
        "updated_at": now_str(),
        "final_system_objective": FINAL_SYSTEM_OBJECTIVE,
        "validation_protocol": VALIDATION_PROTOCOL,
        "abandoned_scope": ABANDONED_SCOPE,
        "status": status,
        "ready_count": len(items) - len(missing),
        "total_count": len(items),
        "public_supplement_status": public_supplement.get("status") or "missing",
        "public_candidate_financial_coverage": int(candidate_financials.get("complete") or 0),
        "checks": items,
        "missing": missing,
        "parallel_progress": {
            category: {
                "ready": sum(1 for item in items if item["category"] == category and item["ready"]),
                "total": sum(1 for item in items if item["category"] == category),
                "blocked_by_stable_strategy": category == "research_evidence",
            }
            for category in ("data", "research_evidence", "execution")
        },
        "strategy_gate_policy": {
            "may_remain_unpassed_indefinitely": True,
            "meaning": "没有证据证明成本后存在稳定优势时不输出正式推荐，而不是降低门槛",
            "blocks": ["formal_recommendation_activation"],
            "does_not_block": [
                "data_backfill",
                "execution_simulator",
                "portfolio_risk_engine",
                "realtime_feed",
                "recommendation_instruction_contract",
                "order_state_machine",
            ],
            "abandoned": ["broker_automated_execution", "broker_real_order_submission"],
        },
        "next_phase": [
            "保持推荐策略研发与样本外门禁，不接入券商",
            "用纸面执行模拟校验推荐在T+1/涨跌停/费用下的可成交性",
            "完善推荐指令契约与操作区间，供人工决策参考",
            "稳定策略晋级后才允许正式推荐激活（仍不自动下单）",
        ],
        "automation": {
            "auto_continue": True,
            "trigger": "dependency_fingerprint_or_new_trading_day",
            "sequence": [
                "market_regime", "raw_unadjusted_prices", "st_and_suspension_events",
                "execution_constraints", "t_minus_60_parallel_research",
                "immutable_forward_shadow", "recommendations", "trade_plans",
                "readiness_audit",
            ],
            "pause_when": [
                "external_source_or_permission_required",
                "same_frozen_oos_would_be_reused_for_parameter_tuning",
                "recent_60_diagnostic_would_be_used_for_model_selection",
                "forward_shadow_would_be_evaluated_before_60_trading_days",
                "data_quality_gate_failed",
            ],
            "resume_when": "blocking_dependency_changes",
            "forbidden_until_authorized": [
                "automatic_threshold_tuning",
                "using_recent_60_diagnostic_for_promotion",
                "overwriting_forward_shadow_signals",
                "broker_real_order_submission",
                "silent_gate_relaxation",
            ],
            "permanently_out_of_scope": [
                "broker_order_gateway",
                "broker_automated_execution",
            ],
        },
        "authority": authority_policy(),
    }
    _write(data / "iteration/trading_readiness.json", payload)
    _write(data / "iteration/authority_policy.json", payload["authority"])
    return payload
