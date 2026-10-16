"""Transparent conditional ETAs for recommendation-only readiness (no broker)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.time_utils import now_str


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


def _weekday_after(start: date, trading_days: int) -> date:
    """Conservative weekday estimate; exchange calendar may move the date later."""
    current = start
    remaining = trading_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def build_iteration_eta(
    cfg: CrawlerConfig | None = None,
    *,
    now: datetime | None = None,
    next_run_after: str | None = None,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    now = now or datetime.now()
    data = cfg.data_dir
    readiness = _read(data / "iteration/trading_readiness.json")
    robust = _read(data / "strategy_iterations/latest.json")
    acquisition = _read(data / "acquisition/status.json")
    forward = _read(data / "forward_shadow/status.json")
    missing = {str(row.get("name")) for row in readiness.get("missing") or []}
    promoted = bool(robust.get("promotion_passed")) or (
        forward.get("status") == "evaluated"
        and bool(forward.get("promotion_passed"))
        and str(forward.get("decision") or "") == "promote_from_forward_shadow"
    )
    shadow_days = int(forward.get("recorded_trading_days") or 0)
    remaining_shadow = max(0, 60 - shadow_days)
    earliest_shadow_end = _weekday_after(now.date(), remaining_shadow)

    active_total = int(acquisition.get("total") or 0)
    active_completed = int(acquisition.get("completed") or 0)
    execution_missing = {
        "execution_simulator",
        "portfolio_risk_engine",
        "recommendation_instruction_engine",
        "order_state_machine",
    } & missing
    # Also accept legacy name during transition.
    if "realtime_trade_instruction_engine" in missing:
        execution_missing.add("recommendation_instruction_engine")

    stages = [
        {
            "name": "当前后台迭代轮次",
            "status": "running",
            "expected_at": (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "confidence": "low" if active_total and active_completed == 0 else "medium",
            "basis": f"全量采集 {active_completed}/{active_total}" if active_total else "依赖图增量执行",
        },
        {
            "name": "数据层补齐",
            "status": "complete" if not ({"candidate_full_financials_verified", "announcements_point_in_time"} & missing) else "in_progress",
            "expected_at": None if not ({"candidate_full_financials_verified", "announcements_point_in_time"} & missing)
            else (now + timedelta(days=1)).strftime("%Y-%m-%d 18:00:00"),
            "confidence": "medium",
            "basis": "公开源、候选三表、公告时点核验",
        },
        {
            "name": "推荐执行校验基础设施",
            "status": "complete" if not execution_missing else "pending",
            "expected_at": None if not execution_missing else (now + timedelta(days=1)).strftime("%Y-%m-%d 18:00:00"),
            "confidence": "high" if not execution_missing else "medium",
            "basis": (
                "纸面执行模拟器、组合风控、推荐指令契约、订单状态机已就绪"
                if not execution_missing
                else f"仍缺: {', '.join(sorted(execution_missing))}"
            ),
        },
        {
            "name": "稳定推荐策略与前向观察",
            "status": (
                "evaluation_due" if promoted and remaining_shadow == 0
                else "waiting_for_stable_strategy" if not promoted
                else "observing"
            ),
            "expected_at": earliest_shadow_end.isoformat() if not promoted or remaining_shadow else now.date().isoformat(),
            "confidence": "conditional",
            "basis": (
                "若今天冻结出合格策略，至少再观察60个交易日；当前尚无稳定晋级策略"
                if not promoted else f"不可覆盖前向账本尚余 {remaining_shadow} 个交易日"
            ),
        },
    ]

    pipeline_ready = readiness.get("status") in {
        "recommendation_ready",
        "recommendation_pipeline_ready",
    }
    formal_ready = readiness.get("status") == "recommendation_ready" and promoted
    if formal_ready:
        final_display = now.date().isoformat()
        final_expected = now.date().isoformat()
        confidence = "high"
    elif pipeline_ready and not promoted:
        final_display = (
            f"推荐流水线已可用；正式推荐激活待稳定策略晋级"
            f"（前向观察条件性最早 {earliest_shadow_end.isoformat()}）"
        )
        final_expected = None
        confidence = "conditional"
    else:
        final_display = (
            f"条件性最早 {earliest_shadow_end.isoformat()}；"
            "仅推荐模式，不接入券商；正式推荐待策略晋级与执行校验齐备"
        )
        final_expected = None
        confidence = "conditional"

    payload = {
        "updated_at": now_str(),
        "product_mode": "recommendation_only",
        "broker_integration": False,
        "next_iteration_check_at": next_run_after or (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
        "current_iteration_expected_at": stages[0]["expected_at"],
        "stages": stages,
        "fast_track": {
            "mode": "recommendation_paper_validation",
            "simulation_ready_expected_at": (
                None if not execution_missing
                else (now + timedelta(days=1)).strftime("%Y-%m-%d 18:00:00")
            ),
            "scope": [
                "实时行情",
                "推荐与操作区间",
                "纸面执行模拟器",
                "组合风险检查",
                "推荐指令契约",
                "纸面订单状态机",
            ],
            "excludes": [
                "真实券商报单",
                "券商网关",
                "自动交易",
            ],
            "reason": "当前方案只做推荐策略；执行层仅服务纸面可成交校验与人工参考",
        },
        "final_completion": {
            "earliest_at": earliest_shadow_end.isoformat(),
            "expected_at": final_expected,
            "display": final_display,
            "confidence": confidence,
            "blocking_conditions": [
                text for condition, text in (
                    (bool(execution_missing), f"推荐执行校验仍缺: {', '.join(sorted(execution_missing))}"),
                    (not promoted, "稳定策略尚未通过冻结样本外与前向门禁"),
                    (remaining_shadow > 0, f"前向影子观察尚余至少{remaining_shadow}个交易日"),
                ) if condition
            ],
        },
        "policy": [
            "ETA按实际缺失项计算，已完成阶段不再按日历后移",
            "放弃券商自动交易后，完成定义改为推荐流水线可用",
            "正式推荐激活仍要求稳定策略证据，不降低研究门禁",
        ],
    }
    _write(data / "iteration/eta.json", payload)
    return payload
