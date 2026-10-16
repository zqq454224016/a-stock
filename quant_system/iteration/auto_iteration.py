"""Evaluate strategy/data gates and produce a non-destructive iteration plan."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

POLICY_VERSION = "1.0.0"
POLICY = {
    "minimum_history_bars": 1250,
    "minimum_universe_count": 2000,
    "minimum_oos_samples": 100,
    "minimum_weighted_hit_rate": 0.55,
    "minimum_avg_signed_return_pct": 0.0,
    "minimum_eligible_coverage": 0.10,
    "minimum_avg_max_adverse_pct": -15.0,
}

CLEANUP_CANDIDATES = [
    {
        "wave": "B",
        "module": "quant_system/tasks/replay_job.py",
        "replacement": "strategy_backtest + purged walk-forward",
        "remove_after": "purged/embargo validation is active",
    },
    {
        "wave": "B",
        "module": "quant_system/tasks/predict_job.py",
        "replacement": "calibrated multi-horizon probability",
        "remove_after": "probability calibration passes Brier and bucket checks",
    },
    {
        "wave": "B",
        "module": "quant_system/tasks/selector_job.py",
        "replacement": "market-gated recommendation pipeline",
        "remove_after": "frozen candidate hindsight review is active",
    },
    {
        "wave": "B",
        "module": "quant_system/tasks/decision_job.py",
        "replacement": "structured research conclusion",
        "remove_after": "web and AI no longer consume decisions",
    },
    {
        "wave": "B",
        "module": "quant_system/tasks/agent_job.py",
        "replacement": "Codex evidence review",
        "remove_after": "audit metadata is migrated",
    },
    {
        "wave": "B",
        "module": "quant_system/tasks/sim_trade_job.py",
        "replacement": "cost-aware shadow portfolio",
        "remove_after": "T+1, price limits and costs are enforced",
    },
]


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _validation_metrics(index: dict[str, Any]) -> dict[str, Any]:
    items = list(index.get("items") or [])
    sample_total = 0
    hit_total = 0.0
    return_total = 0.0
    adverse_total = 0.0
    eligible = 0
    evaluated = 0
    for item in items:
        metrics = item.get("20d") or {}
        samples = int(metrics.get("sample_count") or 0)
        if not samples:
            continue
        hit_rate = float(metrics.get("hit_rate") or 0)
        signed_return = float(metrics.get("avg_signed_return_pct") or 0)
        adverse = float(metrics.get("max_adverse_pct") or 0)
        sample_total += samples
        hit_total += hit_rate * samples
        return_total += signed_return * samples
        adverse_total += adverse * samples
        evaluated += 1
        if (
            samples >= POLICY["minimum_oos_samples"]
            and hit_rate >= POLICY["minimum_weighted_hit_rate"]
            and signed_return > POLICY["minimum_avg_signed_return_pct"]
        ):
            eligible += 1
    return {
        "evaluated_stocks": evaluated,
        "sample_count": sample_total,
        "weighted_hit_rate": round(hit_total / sample_total, 4) if sample_total else None,
        "weighted_avg_signed_return_pct": round(return_total / sample_total, 4) if sample_total else None,
        "weighted_avg_max_adverse_pct": round(adverse_total / sample_total, 4) if sample_total else None,
        "eligible_stocks": eligible,
        "eligible_coverage": round(eligible / evaluated, 4) if evaluated else 0.0,
    }


def _gate(name: str, actual: Any, required: Any, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "actual": actual, "required": required, "passed": passed, "detail": detail}


def build_iteration_status(data_dir: Path, project_root: Path) -> dict[str, Any]:
    quality = _read(data_dir / "quality/latest.json")
    universe = _read(data_dir / "universe/stocks.json")
    interim = _read(data_dir / "interim_reports/index.json")
    validation_index = _read(data_dir / "strategy_backtest/index.json")
    validation = _validation_metrics(validation_index)
    quality_rows = list(quality.get("stocks") or [])
    max_history_bars = max((int(row.get("rows") or 0) for row in quality_rows), default=0)
    universe_rows = universe.get("stocks") if isinstance(universe.get("stocks"), list) else universe.get("items")
    if not isinstance(universe_rows, list):
        universe_rows = []
    coded_rows = [row for row in universe_rows if isinstance(row, dict) and row.get("code")]
    universe_count = sum(
        1 for row in coded_rows if is_research_stock_code(str(row.get("code") or ""))
    ) if coded_rows else len(universe_rows)
    if not universe_count:
        universe_count = int(universe.get("count") or 0)
    financial_status = str(interim.get("status") or "missing")

    gates = [
        _gate("history_length", max_history_bars, POLICY["minimum_history_bars"], max_history_bars >= POLICY["minimum_history_bars"], "至少五年交易日"),
        _gate("universe_count", universe_count, POLICY["minimum_universe_count"], universe_count >= POLICY["minimum_universe_count"], "普通研究池必须具备足够横截面"),
        _gate("point_in_time_financials", financial_status, "complete_or_partial", financial_status in {"complete", "partial"}, "财务数据必须带发布时间和可知时间"),
        _gate("oos_sample_count", validation["sample_count"], POLICY["minimum_oos_samples"], validation["sample_count"] >= POLICY["minimum_oos_samples"], "20日样本外聚合样本"),
        _gate("weighted_hit_rate", validation["weighted_hit_rate"], POLICY["minimum_weighted_hit_rate"], (validation["weighted_hit_rate"] or 0) >= POLICY["minimum_weighted_hit_rate"], "不能只报告最佳股票"),
        _gate("avg_signed_return", validation["weighted_avg_signed_return_pct"], f">{POLICY['minimum_avg_signed_return_pct']}", (validation["weighted_avg_signed_return_pct"] or 0) > POLICY["minimum_avg_signed_return_pct"], "当前仍为成本前指标"),
        _gate("eligible_coverage", validation["eligible_coverage"], POLICY["minimum_eligible_coverage"], validation["eligible_coverage"] >= POLICY["minimum_eligible_coverage"], "防止靠极少数信号抬高命中率"),
        _gate("avg_max_adverse", validation["weighted_avg_max_adverse_pct"], POLICY["minimum_avg_max_adverse_pct"], validation["weighted_avg_max_adverse_pct"] is not None and validation["weighted_avg_max_adverse_pct"] >= POLICY["minimum_avg_max_adverse_pct"], "后续替换为成本后组合回撤"),
    ]
    failed = [gate["name"] for gate in gates if not gate["passed"]]
    data_ready = all(gate["passed"] for gate in gates[:3])
    validation_ready = all(gate["passed"] for gate in gates[3:])
    if not data_ready:
        phase = "data_foundation"
    elif not validation_ready:
        phase = "offline_validation"
    else:
        phase = "shadow_candidate"

    cleanup = [
        {
            **item,
            "exists": (project_root / item["module"]).exists(),
            "status": "retain_until_replacement_gate",
        }
        for item in CLEANUP_CANDIDATES
    ]
    next_actions: list[str] = []
    if max_history_bars < POLICY["minimum_history_bars"]:
        next_actions.append(f"把历史行情从 {max_history_bars} 根扩展到至少 {POLICY['minimum_history_bars']} 根")
    if financial_status not in {"complete", "partial"}:
        next_actions.append("接入有权限的点时财务/公告来源，补齐 published_at 和 known_at")
    if not validation_ready:
        next_actions.append("实现 purged walk-forward、embargo、成本与市场状态分层后重新验证")
    next_actions.append("按退役 Wave B 逐项解除旧模块消费者；自动流程只标记，不自动删除")

    return {
        "policy_version": POLICY_VERSION,
        "updated_at": now_str(),
        "mode": "non_destructive_auto_iteration",
        "phase": phase,
        "strategy_status": "eligible_for_shadow" if not failed else "research_only",
        "promotion_allowed": not failed,
        "data": {
            "max_history_bars": max_history_bars,
            "universe_count": universe_count,
            "quality_total": quality.get("total"),
            "quality_summary": quality.get("summary") or {},
            "point_in_time_financial_status": financial_status,
        },
        "validation": validation,
        "gates": gates,
        "failed_gates": failed,
        "next_actions": next_actions,
        "cleanup_candidates": cleanup,
        "safety": {
            "auto_parameter_tuning": False,
            "auto_code_deletion": False,
            "auto_trading": False,
            "human_review_required": True,
        },
        "limitations": [
            "当前一年验证尚不能替代五年以上多市场状态样本外验证",
            "当前平均方向收益尚未扣除全部交易费用、滑点与冲击成本",
            "晋级门槛修改必须提升 policy_version，不能覆盖旧状态",
        ],
    }


def run_auto_iteration(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    project_root = Path(__file__).resolve().parents[2]
    payload = build_iteration_status(cfg.data_dir, project_root)
    _write(cfg.data_dir / "iteration/status.json", payload)
    from quant_system.iteration.trading_readiness import run_trading_readiness_audit
    run_trading_readiness_audit(cfg)
    return payload
