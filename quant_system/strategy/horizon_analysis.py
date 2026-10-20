"""按短线 / 长线轨道生成互不替代的策略分析报告。"""

from __future__ import annotations

from typing import Any

from quant_system.strategy.horizon_tracks import (
    TRACK_LONG,
    TRACK_SHORT,
    TRACK_SPECS,
    TRACK_SWING,
    candidates_for_track,
    track_for_horizon,
)
from quant_system.utils.time_utils import now_str

ANALYSIS_VERSION = "1.0.0"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _signal_portfolio_gap(metrics: dict[str, Any] | None) -> dict[str, Any]:
    metrics = metrics or {}
    portfolio = metrics.get("portfolio") if isinstance(metrics.get("portfolio"), dict) else {}
    signal_ret = metrics.get("avg_net_return_pct")
    port_ret = portfolio.get("total_return_pct")
    accepted = int(portfolio.get("accepted_trades") or 0)
    rejected = int(portfolio.get("rejected_capacity") or 0)
    starved = accepted > 0 and rejected > accepted * 5
    divergence = (
        signal_ret is not None
        and port_ret is not None
        and _num(signal_ret) > 0
        and _num(port_ret) < 0
    )
    return {
        "signal_avg_net_return_pct": signal_ret,
        "signal_hit_rate": metrics.get("hit_rate"),
        "signal_trades": metrics.get("trades"),
        "portfolio_total_return_pct": port_ret,
        "portfolio_hit_rate": portfolio.get("hit_rate"),
        "portfolio_accepted_trades": accepted,
        "portfolio_rejected_capacity": rejected,
        "signal_positive_portfolio_negative": divergence,
        "capacity_starved": starved,
    }


def _candidate_row(item: dict[str, Any]) -> dict[str, Any]:
    train = item.get("train") or {}
    oos = item.get("oos") or {}
    return {
        "name": item.get("name"),
        "horizon": item.get("horizon"),
        "mode": item.get("mode"),
        "source_id": item.get("source_id"),
        "train_score": item.get("train_score"),
        "train": _signal_portfolio_gap(train),
        "oos": _signal_portfolio_gap(oos),
    }


def _pick_track_leader(
    candidates: list[dict[str, Any]],
    horizon_results: dict[str, Any],
    track: str,
) -> dict[str, Any]:
    track_candidates = candidates_for_track(candidates, track)
    if not track_candidates:
        return {"status": "no_candidates", "selected_candidate": None}
    # Prefer the per-horizon tournament pick when available.
    preferred_names = []
    for horizon, payload in horizon_results.items():
        if track_for_horizon(str(horizon)) != track:
            continue
        name = (payload or {}).get("selected_candidate")
        if name:
            preferred_names.append(str(name))
    by_name = {str(row.get("name")): row for row in track_candidates}
    selected = None
    for name in preferred_names:
        if name in by_name:
            selected = by_name[name]
            break
    if selected is None:
        selected = max(track_candidates, key=lambda row: _num(row.get("train_score"), -1e9))
    horizon = str(selected.get("horizon") or "")
    horizon_payload = horizon_results.get(horizon) or {}
    return {
        "status": "selected",
        "selected_candidate": selected.get("name"),
        "horizon": horizon,
        "promotion_passed_diagnostic": bool(horizon_payload.get("promotion_passed")),
        "evaluation_scope": horizon_payload.get("evaluation_scope"),
        "baseline_candidate": horizon_payload.get("baseline_candidate"),
        "profile": _candidate_row(selected),
        "oos": horizon_payload.get("selected_oos") or selected.get("oos"),
        "baseline_oos": horizon_payload.get("baseline_oos"),
    }


def _parallel_tournament_summary(payload: dict[str, Any], *, label: str) -> dict[str, Any]:
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
    rows = []
    for name, item in strategies.items():
        if not isinstance(item, dict):
            continue
        avg = item.get("avg_net_return_pct")
        rows.append({
            "name": name,
            "mode": item.get("mode"),
            "stocks": item.get("stocks"),
            "trades": item.get("trades"),
            "avg_net_return_pct": avg,
            "avg_hit_rate": item.get("avg_hit_rate") or item.get("hit_rate"),
            "edge_positive": bool(item.get("edge_positive"))
            if item.get("edge_positive") is not None
            else _num(avg, -99) > 0,
        })
    positive = sum(1 for row in rows if row["edge_positive"])
    return {
        "label": label,
        "updated_at": payload.get("updated_at"),
        "status": payload.get("status"),
        "strategy_count": len(rows),
        "positive_edge_count": positive,
        "all_negative": bool(rows) and positive == 0,
        "strategies": rows,
    }


def _overnight_summary(overnight: dict[str, Any]) -> dict[str, Any]:
    return _parallel_tournament_summary(overnight, label="overnight")


def _tail_overnight_summary(tail: dict[str, Any]) -> dict[str, Any]:
    specs = tail.get("specs") if isinstance(tail.get("specs"), dict) else {}
    rows = []
    for name, item in specs.items():
        holdout = item.get("holdout") or {}
        rows.append({
            "name": name,
            "status": item.get("status"),
            "holdout_hit_rate": holdout.get("hit_rate"),
            "holdout_avg_net_return_pct": holdout.get("avg_net_return_pct"),
            "holdout_portfolio_return_pct": (holdout.get("portfolio") or {}).get("total_return_pct"),
            "diagnostic_passed": bool((item.get("gate") or {}).get("diagnostic_passed")),
        })
    passed = [row["name"] for row in rows if row["diagnostic_passed"]]
    return {
        "label": "tail_in_next_day_out",
        "updated_at": tail.get("updated_at"),
        "selected_by_development": tail.get("selected_by_development"),
        "diagnostic_passed": passed,
        "none_passed": bool(rows) and not passed,
        "strategies": rows,
    }


def _recommendation_summary(recommendation: dict[str, Any]) -> dict[str, Any]:
    periods = recommendation.get("periods") or {}
    short = periods.get("short") or {}
    aggressive = periods.get("aggressive") or {}
    miss = recommendation.get("miss_audit") if isinstance(recommendation.get("miss_audit"), dict) else {}
    return {
        "recommendation_version": recommendation.get("recommendation_version"),
        "regime": (recommendation.get("market_context") or {}).get("regime"),
        "short_recommendation_count": len(short.get("recommendations") or []),
        "aggressive_recommendation_count": len(aggressive.get("recommendations") or []),
        "anti_chase_exclusion_count": miss.get("anti_chase_exclusion_count"),
        "numerical_ready_count": miss.get("numerical_ready_count"),
        "pipeline_intraday_defect": miss.get("pipeline_intraday_defect"),
        "examples": miss.get("examples") or [],
        "promotion_alignment": miss.get("promotion_alignment"),
    }


def _long_quality_readiness(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    target = next(
        (row for row in candidates if row.get("name") == "long_quality_trend_gate"),
        None,
    )
    if not target:
        return {"status": "candidate_missing", "ready": False}
    train = target.get("train") or {}
    oos = target.get("oos") or {}
    trades = int((train.get("trades") or 0) or 0) + int((oos.get("trades") or 0) or 0)
    return {
        "status": "present",
        "ready": trades > 0,
        "train_trades": train.get("trades"),
        "oos_trades": oos.get("trades"),
        "note": (
            "点时财务已产生信号，可进入长线诊断"
            if trades > 0
            else "点时财务未 join 或质量门全关，长线质量候选当前为空信号（失败关闭）"
        ),
    }


def _verdict_short(
    leader: dict[str, Any],
    overnight: dict[str, Any],
    recommendation: dict[str, Any],
    aggressive: dict[str, Any] | None = None,
    tail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = (leader.get("profile") or {}).get("oos") or {}
    aggressive = aggressive or {}
    tail = tail or {}
    issues = []
    if overnight.get("all_negative"):
        issues.append("隔夜三流代理收益均为负，短线形态边未成立")
    if tail.get("none_passed"):
        issues.append("尾盘进次日出10个预登记组合均未过回测门禁")
    if aggressive.get("all_negative"):
        issues.append("激进板并行三流代理收益均为负，强势突破边未成立")
    if profile.get("capacity_starved") or profile.get("signal_positive_portfolio_negative"):
        issues.append("短线研究边在组合容量下消失或信号/组合背离")
    if not leader.get("promotion_passed_diagnostic"):
        issues.append("short 诊断窗未过晋级条款")
    if (recommendation.get("short_recommendation_count") or 0) == 0:
        issues.append("正式短线推荐为空（可能含反追涨设计排除）")
    if (recommendation.get("aggressive_recommendation_count") or 0) == 0 and aggressive.get("all_negative"):
        issues.append("正式激进板为空且研究代理无正边")
    if not issues:
        return {
            "verdict": "short_track_diagnostic_ok_wait_policy",
            "summary": "短线诊断指标可继续观察，仍须政策与前向影子，不可同窗调参晋级。",
            "issues": [],
        }
    return {
        "verdict": "short_track_strategy_or_design_hold",
        "summary": "短线轨尚未具备可推荐边：" + "；".join(issues) + "。",
        "issues": issues,
    }


def _verdict_long(leader: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    issues = []
    if not quality.get("ready"):
        issues.append("长线质量门缺少点时财务信号")
    if not leader.get("promotion_passed_diagnostic"):
        issues.append("medium/long 诊断窗未过晋级条款")
    profile = (leader.get("profile") or {}).get("oos") or {}
    if profile.get("signal_positive_portfolio_negative"):
        issues.append("长线候选信号/组合背离")
    if not issues:
        return {
            "verdict": "long_track_diagnostic_ok_wait_policy",
            "summary": "长线诊断可继续前向观察；正式长线推荐仍未启用。",
            "issues": [],
        }
    return {
        "verdict": "long_track_not_ready",
        "summary": "长线轨未就绪：" + "；".join(issues) + "。",
        "issues": issues,
    }


def build_horizon_analysis(
    *,
    strategy_iteration: dict[str, Any],
    overnight_iteration: dict[str, Any] | None = None,
    aggressive_board_iteration: dict[str, Any] | None = None,
    tail_overnight_iteration: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = list(strategy_iteration.get("candidates") or [])
    horizon_results = strategy_iteration.get("horizon_results") or {}
    overnight = _overnight_summary(overnight_iteration or {})
    aggressive = _parallel_tournament_summary(
        aggressive_board_iteration or {}, label="aggressive_board"
    )
    tail = _tail_overnight_summary(tail_overnight_iteration or {})
    rec = _recommendation_summary(recommendation or {})
    quality = _long_quality_readiness(candidates)

    short_leader = _pick_track_leader(candidates, horizon_results, TRACK_SHORT)
    long_leader = _pick_track_leader(candidates, horizon_results, TRACK_LONG)
    swing_leader = _pick_track_leader(candidates, horizon_results, TRACK_SWING)

    short_payload = {
        "track": TRACK_SHORT,
        "spec": TRACK_SPECS[TRACK_SHORT],
        "leader": short_leader,
        "candidate_count": len(candidates_for_track(candidates, TRACK_SHORT)),
        "candidates": [_candidate_row(row) for row in candidates_for_track(candidates, TRACK_SHORT)],
        "overnight": overnight,
        "aggressive_board": aggressive,
        "tail_overnight": tail,
        "formal_recommendation": rec,
        "analysis": _verdict_short(short_leader, overnight, rec, aggressive, tail),
    }
    long_payload = {
        "track": TRACK_LONG,
        "spec": TRACK_SPECS[TRACK_LONG],
        "leader": long_leader,
        "candidate_count": len(candidates_for_track(candidates, TRACK_LONG)),
        "candidates": [_candidate_row(row) for row in candidates_for_track(candidates, TRACK_LONG)],
        "quality_gate": quality,
        "analysis": _verdict_long(long_leader, quality),
    }
    swing_payload = {
        "track": TRACK_SWING,
        "spec": TRACK_SPECS[TRACK_SWING],
        "leader": swing_leader,
        "candidate_count": len(candidates_for_track(candidates, TRACK_SWING)),
        "note": "波段仅作对照，不替代短线或长线结论",
        "analysis": {
            "verdict": "swing_context_only",
            "summary": (
                f"全局研究常选中 swing（当前源 selected={strategy_iteration.get('selected_candidate')} / "
                f"{strategy_iteration.get('selected_horizon')}），分析长短线时必须拆开看，避免被波段冠军带偏。"
            ),
        },
    }

    return {
        "status": "complete",
        "analysis_version": ANALYSIS_VERSION,
        "updated_at": now_str(),
        "source": {
            "strategy_run_id": strategy_iteration.get("run_id"),
            "research_version": strategy_iteration.get("research_version"),
            "global_selected_candidate": strategy_iteration.get("selected_candidate"),
            "global_selected_horizon": strategy_iteration.get("selected_horizon"),
            "decision": strategy_iteration.get("decision"),
            "promotion_passed": strategy_iteration.get("promotion_passed"),
        },
        "separation_rule": (
            "短线与长线分轨分析、分轨结论；全局 selected_candidate 只作兼容字段，"
            "不得单独代表短线或长线是否可推荐。"
        ),
        "tracks": {
            TRACK_SHORT: short_payload,
            TRACK_LONG: long_payload,
            TRACK_SWING: swing_payload,
        },
        "comparison": {
            "short_verdict": short_payload["analysis"]["verdict"],
            "long_verdict": long_payload["analysis"]["verdict"],
            "do_not_mix": [
                "不把远东类短线大涨未荐解释成长线失效",
                "不把 swing 组合问题直接当成短线正式推荐门禁应放宽",
                "长线未就绪时保持研究空仓，不借用短线筛选凑标的",
            ],
        },
    }
