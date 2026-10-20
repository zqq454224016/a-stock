"""Adversarial audit: is long-term non-promotion a strategy defect or a gate/policy artifact?

Reads strategy_iterations/latest.json and recomputes promotion clauses, signal-vs-portfolio
divergence, contamination scope, and capacity stress without retuning on the same OOS.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.robust_iteration import (
    MIN_SEGMENT_TRADES,
    MIN_TRAIN_TRADES,
    promotion_passed,
)
from quant_system.utils.time_utils import now_str

AUDIT_VERSION = "1.1.0"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _promotion_clauses(
    champion: dict[str, Any],
    baseline: dict[str, Any],
    stability: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    stable = stability or []
    clauses = [
        {
            "id": "stability_segment_count",
            "required": ">=2 development segments",
            "actual": len(stable),
            "passed": len(stable) >= 2,
        },
    ]
    for index, segment in enumerate(stable):
        name = ("early", "late")[index] if index < 2 else f"segment_{index}"
        trades = int(segment.get("trades") or 0)
        avg_ret = _num(segment.get("avg_net_return_pct"), -99)
        med_ret = _num(segment.get("median_net_return_pct"), -99)
        clauses.append({
            "id": f"stability_{name}_trades",
            "required": f">={MIN_SEGMENT_TRADES}",
            "actual": trades,
            "passed": trades >= MIN_SEGMENT_TRADES,
        })
        clauses.append({
            "id": f"stability_{name}_avg_net_return",
            "required": ">0",
            "actual": avg_ret,
            "passed": avg_ret > 0,
        })
        clauses.append({
            "id": f"stability_{name}_median_net_return",
            "required": ">0",
            "actual": med_ret,
            "passed": med_ret > 0,
        })
    hit_floor = max(0.54, _num(baseline.get("hit_rate")))
    avg_floor = max(0.0, _num(baseline.get("avg_net_return_pct"), -99))
    dd_floor = _num(baseline.get("max_drawdown_pct"), -100)
    champion_port = champion.get("portfolio") if isinstance(champion.get("portfolio"), dict) else {}
    baseline_port = baseline.get("portfolio") if isinstance(baseline.get("portfolio"), dict) else {}
    clauses.extend([
        {
            "id": "oos_trades",
            "required": ">=300",
            "actual": int(champion.get("trades") or 0),
            "passed": int(champion.get("trades") or 0) >= 300,
        },
        {
            "id": "oos_hit_rate_vs_baseline",
            "required": f">={hit_floor:.4f}",
            "actual": _num(champion.get("hit_rate")),
            "passed": _num(champion.get("hit_rate")) >= hit_floor,
        },
        {
            "id": "oos_avg_net_return_vs_baseline",
            "required": f">{avg_floor:.4f}",
            "actual": _num(champion.get("avg_net_return_pct"), -99),
            "passed": _num(champion.get("avg_net_return_pct"), -99) > avg_floor,
        },
        {
            "id": "oos_median_net_return",
            "required": ">0",
            "actual": _num(champion.get("median_net_return_pct"), -99),
            "passed": _num(champion.get("median_net_return_pct"), -99) > 0,
        },
        {
            "id": "oos_drawdown_not_worse_than_baseline",
            "required": f">={dd_floor:.4f}",
            "actual": _num(champion.get("max_drawdown_pct"), -100),
            "passed": _num(champion.get("max_drawdown_pct"), -100) >= dd_floor,
        },
        {
            "id": "portfolio_accepted_trades",
            "required": ">=30",
            "actual": int(champion_port.get("accepted_trades") or 0),
            "passed": int(champion_port.get("accepted_trades") or 0) >= 30,
        },
        {
            "id": "portfolio_not_capacity_starved",
            "required": "rejected_capacity <= 5 * accepted_trades",
            "actual": {
                "accepted": int(champion_port.get("accepted_trades") or 0),
                "rejected_capacity": int(champion_port.get("rejected_capacity") or 0),
            },
            "passed": not (
                int(champion_port.get("accepted_trades") or 0) > 0
                and int(champion_port.get("rejected_capacity") or 0)
                > int(champion_port.get("accepted_trades") or 0) * 5
            ),
        },
        {
            "id": "portfolio_total_return_positive",
            "required": ">0",
            "actual": champion_port.get("total_return_pct"),
            "passed": _num(champion_port.get("total_return_pct"), -99) > 0,
        },
        {
            "id": "portfolio_beats_baseline",
            "required": f">{_num(baseline_port.get('total_return_pct'), -99):.4f}",
            "actual": champion_port.get("total_return_pct"),
            "passed": _num(champion_port.get("total_return_pct"), -99)
            > _num(baseline_port.get("total_return_pct"), -99),
        },
        {
            "id": "portfolio_hit_rate",
            "required": ">=0.50",
            "actual": champion_port.get("hit_rate"),
            "passed": champion_port.get("hit_rate") is not None
            and _num(champion_port.get("hit_rate")) >= 0.50,
        },
    ])
    recomputed = promotion_passed(champion, baseline, stable)
    clauses.append({
        "id": "promotion_passed_recomputed",
        "required": True,
        "actual": recomputed,
        "passed": recomputed,
    })
    return clauses


def _signal_vs_portfolio(metrics: dict[str, Any] | None) -> dict[str, Any]:
    metrics = metrics or {}
    portfolio = metrics.get("portfolio") or {}
    signal_ret = None if metrics.get("avg_net_return_pct") is None else _num(metrics.get("avg_net_return_pct"))
    port_ret_n = None if portfolio.get("total_return_pct") is None else _num(portfolio.get("total_return_pct"))
    accepted = int(portfolio.get("accepted_trades") or 0)
    rejected = int(portfolio.get("rejected_capacity") or 0)
    trades = int(metrics.get("trades") or 0)
    acceptance = _num(portfolio.get("acceptance_rate"))
    if acceptance <= 0 and (accepted + rejected) > 0:
        acceptance = accepted / (accepted + rejected)
    divergence = None
    if signal_ret is not None and port_ret_n is not None:
        # Signal avg is per-trade percent; portfolio is path return. Flag when signs disagree
        # or portfolio is deeply negative while signal looks positive.
        divergence = (
            (signal_ret > 0 and port_ret_n < 0)
            or (signal_ret > 0.3 and port_ret_n < -5)
        )
    return {
        "signal_trades": trades,
        "signal_hit_rate": metrics.get("hit_rate"),
        "signal_avg_net_return_pct": metrics.get("avg_net_return_pct"),
        "signal_median_net_return_pct": metrics.get("median_net_return_pct"),
        "portfolio_accepted_trades": accepted,
        "portfolio_rejected_capacity": rejected,
        "portfolio_acceptance_rate": round(acceptance, 4),
        "portfolio_hit_rate": portfolio.get("hit_rate"),
        "portfolio_total_return_pct": portfolio.get("total_return_pct"),
        "portfolio_max_drawdown_pct": portfolio.get("max_drawdown_pct"),
        "signal_positive_portfolio_negative": bool(divergence),
        "capacity_starved": acceptance < 0.08 and rejected > accepted * 5,
    }


def _eligible_gate(candidate: dict[str, Any]) -> dict[str, Any]:
    train = candidate.get("train") or {}
    stability = candidate.get("development_stability") or []
    checks = [
        {
            "id": "train_trades",
            "passed": int(train.get("trades") or 0) >= MIN_TRAIN_TRADES,
            "actual": int(train.get("trades") or 0),
            "required": MIN_TRAIN_TRADES,
        },
        {
            "id": "train_avg_net_return",
            "passed": _num(train.get("avg_net_return_pct"), -99) > 0,
            "actual": train.get("avg_net_return_pct"),
            "required": ">0",
        },
    ]
    for index, segment in enumerate(stability):
        checks.append({
            "id": f"dev_segment_{index}_avg_net_return",
            "passed": _num(segment.get("avg_net_return_pct"), -99) > 0,
            "actual": segment.get("avg_net_return_pct"),
            "required": ">0",
        })
    return {
        "eligible": all(row["passed"] for row in checks),
        "checks": checks,
    }


def run_strategy_adversarial_audit(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "strategy_iterations"
    latest = _read(root / "latest.json")
    if not latest:
        payload = {
            "status": "missing_strategy_iteration",
            "audit_version": AUDIT_VERSION,
            "updated_at": now_str(),
            "verdict": "inconclusive",
            "summary": "缺少 strategy_iterations/latest.json，无法对抗校验",
        }
        _write(root / "adversarial_audit.json", payload)
        return payload

    candidates = list(latest.get("candidates") or [])
    by_name = {str(row.get("name")): row for row in candidates if isinstance(row, dict)}
    selected_name = str(latest.get("selected_candidate") or "")
    selected = by_name.get(selected_name) or {}
    baseline_names = {
        "short": "baseline_short",
        "swing": "baseline_long_only",
        "medium": "baseline_medium",
        "long": "baseline_long",
    }
    horizon = str(latest.get("selected_horizon") or selected.get("horizon") or "swing")
    baseline = by_name.get(baseline_names.get(horizon, "baseline_long_only")) or {}

    champion_oos = selected.get("oos") or latest.get("selected_oos") or {}
    baseline_oos = baseline.get("oos") or latest.get("baseline_oos") or {}
    stability = selected.get("development_stability") or []
    clauses = _promotion_clauses(champion_oos, baseline_oos, stability)
    failed_clauses = [row for row in clauses if not row["passed"]]

    anti = latest.get("anti_overfit") or {}
    historical_blocked = bool(anti.get("historical_oos_can_promote_new_candidates") is False) or bool(
        anti.get("historical_oos_already_observed")
    )
    # Explicit policy in strategy_iteration_job: historical_promotion_blocked = True
    policy_blocks_promotion = True
    diagnostic_passed = list(latest.get("diagnostic_passed_horizons") or [])
    passed_horizons = list(latest.get("passed_horizons") or [])
    horizon_results = latest.get("horizon_results") or {}

    contamination = []
    for name, item in horizon_results.items():
        if not isinstance(item, dict):
            continue
        scope = str(item.get("evaluation_scope") or "")
        contamination.append({
            "horizon": name,
            "evaluation_scope": scope,
            "promotion_passed_reported": bool(item.get("promotion_passed")),
            "contaminated": "diagnostic" in scope or "contaminated" in scope,
        })

    train_gap = _signal_vs_portfolio(selected.get("train"))
    oos_gap = _signal_vs_portfolio(champion_oos)
    eligibility = _eligible_gate(selected) if selected else {"eligible": False, "checks": []}

    # Adversarial family: how many candidates look spuriously good at signal OOS?
    positive_signal_oos = []
    negative_portfolio_train = []
    for row in candidates:
        oos = row.get("oos") or {}
        train = row.get("train") or {}
        if _num(oos.get("avg_net_return_pct"), -99) > 0 and _num(oos.get("hit_rate")) >= 0.54:
            positive_signal_oos.append(row.get("name"))
        port = (train.get("portfolio") or {})
        if _num(port.get("total_return_pct"), 0) < -5:
            negative_portfolio_train.append(row.get("name"))

    regime_only = False
    params = selected.get("parameters") or {}
    allowed = params.get("allowed_regimes") or ()
    if allowed:
        regime_only = True

    attacks = [
        {
            "id": "policy_historical_oos_block",
            "question": "正式晋级是否被历史OOS污染策略硬阻断？",
            "finding": policy_blocks_promotion and bool(diagnostic_passed) and not passed_horizons,
            "detail": (
                f"diagnostic_passed={diagnostic_passed}, passed_horizons={passed_horizons}, "
                "historical_oos_can_promote_new_candidates=false"
            ),
            "implies": "policy_hold" if (policy_blocks_promotion and diagnostic_passed) else None,
        },
        {
            "id": "metric_clause_failure",
            "question": "忽略政策阻断后，晋级公式本身是否仍失败？",
            "finding": bool(failed_clauses),
            "detail": [row["id"] for row in failed_clauses],
            "implies": "strategy_defect" if failed_clauses else "metrics_ok",
        },
        {
            "id": "signal_portfolio_divergence",
            "question": "信号级赚钱但组合级亏损？",
            "finding": bool(train_gap.get("signal_positive_portfolio_negative") or oos_gap.get("signal_positive_portfolio_negative")),
            "detail": {"train": train_gap, "oos": oos_gap},
            "implies": "strategy_untradeable_edge" if (
                train_gap.get("signal_positive_portfolio_negative")
                or oos_gap.get("signal_positive_portfolio_negative")
            ) else None,
        },
        {
            "id": "capacity_starvation",
            "question": "容量拒单是否吃掉绝大部分信号？",
            "finding": bool(train_gap.get("capacity_starved") or oos_gap.get("capacity_starved")),
            "detail": {
                "train_acceptance": train_gap.get("portfolio_acceptance_rate"),
                "oos_acceptance": oos_gap.get("portfolio_acceptance_rate"),
            },
            "implies": "strategy_capacity_fragile" if (
                train_gap.get("capacity_starved") or oos_gap.get("capacity_starved")
            ) else None,
        },
        {
            "id": "regime_concentration",
            "question": "候选是否只允许单一市场状态？",
            "finding": regime_only,
            "detail": {"allowed_regimes": list(allowed) if allowed else []},
            "implies": "strategy_regime_dependent" if regime_only else None,
        },
        {
            "id": "family_wide_weakness",
            "question": "候选族是否整体信号OOS偏弱？",
            "finding": len(positive_signal_oos) <= 2,
            "detail": {
                "positive_signal_oos_count": len(positive_signal_oos),
                "positive_signal_oos": positive_signal_oos[:12],
                "candidate_count": len(candidates),
                "negative_portfolio_train_count": len(negative_portfolio_train),
            },
            "implies": "strategy_hypothesis_space_weak" if len(positive_signal_oos) <= 2 else None,
        },
        {
            "id": "contamination_scope",
            "question": "当前horizon评估是否声明为污染诊断窗？",
            "finding": all(row.get("contaminated") for row in contamination) if contamination else True,
            "detail": contamination,
            "implies": "policy_hold",
        },
        {
            "id": "eligibility_vs_promotion",
            "question": "候选能进eligible但最终无法正式晋级？",
            "finding": bool(eligibility.get("eligible")) and not bool(latest.get("promotion_passed")),
            "detail": eligibility,
            "implies": None,
        },
    ]

    recommendation = _read(cfg.data_dir / "recommendations/summary.json")
    miss = recommendation.get("miss_audit") if isinstance(recommendation.get("miss_audit"), dict) else {}
    examples = list(miss.get("examples") or [])
    anti_chase_examples = [
        row for row in examples if row.get("verdict") == "design_anti_chase_exclusion"
    ]
    attacks.extend([
        {
            "id": "recommendation_intraday_pipeline",
            "question": "正式推荐是否因分时管线缺陷被系统性清零？",
            "finding": bool(miss.get("pipeline_intraday_defect")),
            "detail": {
                "numerical_ready_count": miss.get("numerical_ready_count"),
                "intraday_missing_count": miss.get("intraday_missing_count"),
                "evaluated_count": miss.get("evaluated_count"),
            },
            "implies": "recommendation_pipeline_defect" if miss.get("pipeline_intraday_defect") else None,
        },
        {
            "id": "same_day_chase_not_promotion_target",
            "question": "当日大涨未荐是否属于反追涨设计（非晋级误杀）？",
            "finding": bool(anti_chase_examples) or int(miss.get("anti_chase_exclusion_count") or 0) > 0,
            "detail": {
                "anti_chase_exclusion_count": miss.get("anti_chase_exclusion_count"),
                "examples": anti_chase_examples[:3] or (miss.get("top_gainers_excluded") or [])[:3],
                "promotion_alignment": miss.get("promotion_alignment"),
            },
            "implies": "design_anti_chase_ok",
        },
    ])

    implies = [str(row["implies"]) for row in attacks if row.get("finding") and row.get("implies")]
    strategy_tags = {
        "strategy_defect",
        "strategy_untradeable_edge",
        "strategy_capacity_fragile",
        "strategy_regime_dependent",
        "strategy_hypothesis_space_weak",
    }
    has_strategy = bool(strategy_tags & set(implies))
    has_policy = "policy_hold" in implies
    metrics_ok = "metrics_ok" in implies and not has_strategy
    has_pipeline = "recommendation_pipeline_defect" in implies

    if has_strategy and has_policy:
        verdict = "strategy_defect_and_policy_hold"
        summary = (
            "对抗校验：既有策略层面缺陷（组合/容量/状态依赖或晋级条款失败），"
            "也被历史OOS污染政策阻断正式晋级；即使政策放开，当前证据仍不足以晋级。"
        )
    elif has_strategy:
        verdict = "strategy_defect"
        summary = "对抗校验：失败主要由策略边不足或组合不可交易性导致，不是单纯门禁笔误。"
    elif has_policy and (not failed_clauses or metrics_ok):
        verdict = "policy_hold_only"
        summary = (
            "对抗校验：诊断窗指标可通过，但历史OOS污染政策禁止据此正式晋级；"
            "需等前向影子新观察，不能在同窗调参。"
        )
    else:
        verdict = "inconclusive"
        summary = "对抗校验未能唯一归因，需补充分段稳定性或重跑研究版本。"

    # Stronger wording when train portfolio loses while signal wins.
    if train_gap.get("signal_positive_portfolio_negative"):
        summary += (
            f" 训练段信号均收益为正但组合总收益为"
            f"{train_gap.get('portfolio_total_return_pct')}%，边在容量约束下消失。"
        )
    if has_pipeline:
        summary += " 正式推荐分时管线存在系统性缺失，需先修复量价通过后再拉分时，避免空推荐被误读为策略失效。"
    if "design_anti_chase_ok" in implies:
        summary += " 当日大涨未荐属于反追涨设计（如远东），不是晋级门槛误杀。"

    payload = {
        "status": "complete",
        "audit_version": AUDIT_VERSION,
        "updated_at": now_str(),
        "source_run_id": latest.get("run_id"),
        "research_version": latest.get("research_version"),
        "selected_candidate": selected_name,
        "selected_horizon": horizon,
        "reported_promotion_passed": bool(latest.get("promotion_passed")),
        "reported_decision": latest.get("decision"),
        "diagnostic_passed_horizons": diagnostic_passed,
        "passed_horizons": passed_horizons,
        "verdict": verdict,
        "summary": summary,
        "promotion_clauses": clauses,
        "failed_promotion_clauses": failed_clauses,
        "eligibility": eligibility,
        "signal_vs_portfolio": {"train": train_gap, "oos": oos_gap},
        "adversarial_attacks": attacks,
        "policy": {
            "historical_promotion_blocked": policy_blocks_promotion,
            "historical_oos_already_observed": historical_blocked,
            "recent_60d_diagnostic_cannot_select_or_tune": bool(
                anti.get("recent_60d_diagnostic_cannot_select_or_tune")
            ),
            "oos_used_for_selection": bool(anti.get("oos_used_for_selection")),
        },
        "next_actions": [
            action for condition, action in (
                (
                    has_strategy,
                    "升 research_version，预登记新假设族；禁止在同一OOS上调参",
                ),
                (
                    train_gap.get("signal_positive_portfolio_negative") or train_gap.get("capacity_starved"),
                    "优先改持仓/容量/相关性规则，再测组合级收益是否仍为正",
                ),
                (
                    regime_only,
                    "增加非 rising 状态的对照候选，检验边是否仅为单状态过拟合",
                ),
                (
                    has_policy,
                    "继续不可覆盖前向影子记账；满窗只评估一次，不把诊断窗当晋级证据",
                ),
                (
                    has_pipeline,
                    "先跑量价筛选→只对 numerical_passed 拉分时→再生成正式推荐",
                ),
                (
                    True,
                    "对外保持空正式推荐，直到组合级与政策双重通过；不因远东类大涨放宽反追涨带",
                ),
            )
            if condition
        ],
        "recommendation_miss_audit": miss or None,
    }
    _write(root / "adversarial_audit.json", payload)
    _write(root / "adversarial_audit_history" / f"{now_str().replace(' ', 'T').replace(':', '')}.json", payload)
    return payload


if __name__ == "__main__":
    result = run_strategy_adversarial_audit()
    print(json.dumps({
        "verdict": result.get("verdict"),
        "summary": result.get("summary"),
        "failed_clauses": [row.get("id") for row in result.get("failed_promotion_clauses") or []],
        "next_actions": result.get("next_actions"),
    }, ensure_ascii=False, indent=2))
