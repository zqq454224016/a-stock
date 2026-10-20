"""Immutable forward-shadow ledger, backfilled from the latest 60 real trading days."""

from __future__ import annotations

import gzip
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.long_term_quality import attach_point_in_time_quality
from quant_system.strategy.robust_iteration import (
    CANDIDATES,
    Candidate,
    features,
    signal_mask,
    summarize,
    trades,
)
from quant_system.tasks.strategy_iteration_job import (
    FORWARD_SHADOW_MIN_TRADING_DAYS,
    FORWARD_SHADOW_START,
)
from quant_system.tasks.strategy_job import _read_stock
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

TOP_SIGNALS_PER_DAY = 10
SHADOW_MIN_TRADES = 30
SHADOW_HIT_RATE_FLOOR = 0.54
SHADOW_EVALUATION_PROTOCOL = "1.1.0"  # allow_incomplete_exit at local data end
BASELINE_BY_HORIZON = {
    "short": "baseline_short",
    "swing": "baseline_long_only",
    "medium": "baseline_medium",
    "long": "baseline_long",
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_once(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _iso_date(value: Any) -> str:
    text = str(value or "")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _version_key(value: Any) -> tuple[int, ...] | None:
    text = str(value or "")
    if not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return None
    return tuple(int(part) for part in text.split("."))


def _snapshots(root: Path) -> list[dict[str, Any]]:
    snapshots = []
    for path in (root / "signals").glob("*.json"):
        payload = _read(path)
        trade_date = _iso_date(payload.get("trade_date"))
        version = _version_key(payload.get("strategy_version"))
        if (
            trade_date
            and path.stem == trade_date
            and version is not None
            and payload.get("immutable") is True
        ):
            snapshots.append(payload)
    return sorted(snapshots, key=lambda item: item["trade_date"])


def _iteration_frozen(iteration: dict[str, Any]) -> bool:
    anti_overfit = iteration.get("anti_overfit") or {}
    return bool(
        iteration.get("status") == "complete"
        and _version_key(iteration.get("research_version")) is not None
        and iteration.get("run_id")
        and iteration.get("selected_candidate")
        and anti_overfit.get("candidate_space_frozen") is True
        and anti_overfit.get("forward_shadow_signals_immutable") is True
    )


def _is_preregistered(iteration: dict[str, Any], trade_date: str) -> bool:
    anti_overfit = iteration.get("anti_overfit") or {}
    registered_at = _iso_date(str(iteration.get("updated_at") or "")[:10])
    registered_start = _iso_date(anti_overfit.get("forward_shadow_start"))
    return bool(
        _iteration_frozen(iteration)
        and registered_at
        and registered_at <= trade_date
        and registered_start
        and registered_start <= trade_date
    )


def _resolve_as_of(cfg: CrawlerConfig, recommendations: dict[str, Any]) -> str:
    raw = (recommendations.get("market_context") or {}).get("trade_date")
    trade_date = _iso_date(raw)
    if trade_date:
        return trade_date
    return get_calendar().latest_completed_trade_day()


def historical_shadow_window(
    as_of: str,
    *,
    min_days: int = FORWARD_SHADOW_MIN_TRADING_DAYS,
) -> list[str]:
    """Return the latest ``min_days`` trading days ending at ``as_of`` (inclusive)."""
    as_of = _iso_date(as_of)
    if not as_of:
        return []
    dates = [day for day in get_calendar().fetch_dates() if day <= as_of]
    if not dates:
        return []
    return dates[-min_days:]


def _candidate_by_name(name: str) -> Candidate | None:
    return next((item for item in CANDIDATES if item.name == name), None)


def _load_market_regimes(cfg: CrawlerConfig) -> dict[str, str]:
    payload = _read(cfg.data_dir / "market_regime/five_year.json")
    return {
        str(row.get("date"))[:10]: str(row.get("regime"))
        for row in payload.get("items") or []
        if row.get("date") and row.get("regime")
    }


def _build_historical_signals(
    cfg: CrawlerConfig,
    candidate: Candidate,
    window: list[str],
    market_regimes: dict[str, str],
    *,
    top_n: int = TOP_SIGNALS_PER_DAY,
) -> dict[str, list[dict[str, Any]]]:
    window_set = set(window)
    by_date: dict[str, list[dict[str, Any]]] = {day: [] for day in window}
    stock_dir = cfg.data_dir / "stocks"
    for path in sorted(stock_dir.glob("*.json")):
        if path.stem == "index" or not is_research_stock_code(path.stem):
            continue
        try:
            stock, frame = _read_stock(path)
        except (OSError, ValueError, TypeError):
            continue
        if frame.empty or "ST" in str(stock.get("name") or "").upper():
            continue
        work = attach_point_in_time_quality(features(frame), stock_dir.parent, path.stem)
        date_column = "date" if "date" in work.columns else "trade_date"
        if date_column not in work.columns:
            continue
        work["_date"] = work[date_column].astype(str).str[:10]
        mask = signal_mask(work, candidate).fillna(False)
        if candidate.allowed_regimes:
            regimes = work["_date"].map(market_regimes)
            mask &= regimes.isin(candidate.allowed_regimes)
        code = str(stock.get("code") or path.stem).zfill(6)
        name = str(stock.get("name") or "")
        for index in np.flatnonzero(mask.to_numpy()):
            trade_date = work.at[index, "_date"]
            if trade_date not in window_set:
                continue
            score = work.at[index, "score"]
            by_date[trade_date].append({
                "horizon": candidate.horizon,
                "code": code,
                "name": name,
                "score": round(float(score), 4) if np.isfinite(score) else None,
                "status": "signal",
            })
    for trade_date, rows in by_date.items():
        rows.sort(key=lambda item: (-(item.get("score") or 0.0), item["code"]))
        by_date[trade_date] = rows[:top_n]
    return by_date


def _archive_incompatible(
    root: Path,
    window: list[str],
    *,
    research_version: str,
) -> int:
    """Archive in-window snapshots that belong to another research version."""
    if not window:
        return 0
    start, end = window[0], window[-1]
    archive_root = root / "archived" / now_str().replace(" ", "T").replace(":", "")
    moved = 0
    for path in (root / "signals").glob("*.json"):
        payload = _read(path)
        trade_date = _iso_date(payload.get("trade_date")) or path.stem
        if not (start <= trade_date <= end):
            continue
        if str(payload.get("strategy_version") or "") == research_version:
            continue
        archive_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(archive_root / path.name))
        moved += 1
    return moved


def _status(
    root: Path,
    snapshots: list[dict[str, Any]],
    *,
    result: str,
    trade_date: str | None,
    window: list[str] | None = None,
    created: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = (window[0] if window else "") or _iso_date(FORWARD_SHADOW_START)
    window_set = set(window) if window else None
    eligible_snapshots = [
        item for item in snapshots
        if (not start or item["trade_date"] >= start)
        and (window_set is None or item["trade_date"] in window_set)
    ]
    signal_days = len({item["trade_date"] for item in eligible_snapshots})
    remaining = max(0, FORWARD_SHADOW_MIN_TRADING_DAYS - signal_days)
    previous = _read(root / "status.json")
    locked = previous.get("status") == "evaluated" and previous.get("evaluation_locked") is True
    status = {
        "updated_at": now_str(),
        "status": "evaluated" if locked else ("evaluation_due" if remaining == 0 else "collecting"),
        "result": previous.get("result") if locked else result,
        "start": start,
        "end": window[-1] if window else None,
        "minimum_trading_days": FORWARD_SHADOW_MIN_TRADING_DAYS,
        "recorded_trading_days": signal_days,
        "remaining_trading_days": remaining,
        "progress_pct": round(
            min(1.0, signal_days / max(1, FORWARD_SHADOW_MIN_TRADING_DAYS)) * 100, 2
        ),
        "last_trade_date": eligible_snapshots[-1]["trade_date"] if eligible_snapshots else None,
        "requested_trade_date": trade_date,
        "last_snapshot_created": created,
        "source": "historical_real_window",
        "overwrite_forbidden": True,
        "date_regression_forbidden": True,
        "old_version_pollution_forbidden": True,
        "only_preregistered_versions": True,
    }
    if locked:
        for key in (
            "evaluation_locked", "promotion_passed", "decision", "evaluation_path",
            "selected_candidate", "allowed_regimes", "total_signals", "days_with_signals",
            "fail_reasons",
        ):
            if key in previous and key not in (extra or {}):
                status[key] = previous[key]
    if extra:
        status.update(extra)
    status_path = root / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def _signals_from_recommendations(recommendations: dict[str, Any]) -> list[dict[str, Any]]:
    periods = recommendations.get("periods") or {}
    signals = []
    for horizon in ("short", "medium", "long"):
        for item in (periods.get(horizon) or {}).get("recommendations") or []:
            signals.append({
                "horizon": horizon,
                "code": str(item.get("code") or ""),
                "name": str(item.get("name") or ""),
                "score": item.get("score"),
                "status": item.get("status"),
            })
    return signals


def _regime_coverage(window: list[str], market_regimes: dict[str, str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    missing_days: list[str] = []
    for day in window:
        label = market_regimes.get(day)
        if not label:
            missing_days.append(day)
            label = "missing"
        counts[label] = counts.get(label, 0) + 1
    return {
        "regime_counts": counts,
        "missing_days": missing_days,
        "missing_count": len(missing_days),
        "coverage_complete": len(missing_days) == 0 and bool(window),
        "coverage_pct": round((1 - len(missing_days) / max(1, len(window))) * 100, 2),
    }


def invalidate_incomplete_forward_shadow(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    """Archive a locked evaluation/signals that were built with incomplete inputs/protocol."""
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "forward_shadow"
    evaluation = _read(root / "evaluation.json")
    if not evaluation:
        return {"result": "no_evaluation"}
    regime_counts = evaluation.get("regime_counts") or {}
    missing = int(regime_counts.get("missing") or 0)
    stale_protocol = str(evaluation.get("evaluation_protocol") or "") != SHADOW_EVALUATION_PROTOCOL
    if (
        missing <= 0
        and evaluation.get("regime_coverage_complete") is not False
        and not stale_protocol
    ):
        return {"result": "evaluation_complete_keep", "missing": missing}
    stamp = now_str().replace(" ", "T").replace(":", "")
    reason = "incomplete_regime" if missing > 0 else "stale_protocol"
    archive_root = root / "archived" / f"{reason}_{stamp}"
    archive_root.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in ("evaluation.json", "status.json"):
        path = root / name
        if path.exists():
            shutil.move(str(path), str(archive_root / name))
            moved.append(name)
    signals_dir = root / "signals"
    if signals_dir.exists() and (missing > 0 or evaluation.get("regime_coverage_complete") is False):
        target = archive_root / "signals"
        shutil.move(str(signals_dir), str(target))
        moved.append("signals")
        signals_dir.mkdir(parents=True, exist_ok=True)
    return {
        "result": "invalidated_incomplete_evaluation",
        "reason": reason,
        "missing_regime_days": missing,
        "archived_to": str(archive_root.relative_to(cfg.data_dir)),
        "moved": moved,
    }


def _shadow_promotion_passed(champion: dict[str, Any], baseline: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    trades_n = int(champion.get("trades") or 0)
    if trades_n < SHADOW_MIN_TRADES:
        reasons.append(f"trades<{SHADOW_MIN_TRADES}")
    hit_rate = champion.get("hit_rate")
    floor = max(SHADOW_HIT_RATE_FLOOR, float(baseline.get("hit_rate") or 0))
    if hit_rate is None or float(hit_rate) < floor:
        reasons.append(f"hit_rate<{floor}")
    if float(champion.get("avg_net_return_pct") or -99) <= max(0.0, float(baseline.get("avg_net_return_pct") or 0)):
        reasons.append("avg_net_return_not_above_baseline_and_zero")
    if float(champion.get("median_net_return_pct") or -99) <= 0:
        reasons.append("median_net_return<=0")
    champ_dd = float(champion.get("max_drawdown_pct") or -100)
    base_dd = float(baseline.get("max_drawdown_pct") or -100)
    if champ_dd < base_dd:
        reasons.append("max_drawdown_worse_than_baseline")
    return (not reasons), reasons


def _collect_window_trades(
    cfg: CrawlerConfig,
    candidate: Candidate,
    window: list[str],
    market_regimes: dict[str, str],
) -> pd.DataFrame:
    window_set = set(window)
    parts: list[pd.DataFrame] = []
    for path in sorted((cfg.data_dir / "stocks").glob("*.json")):
        if path.stem == "index" or not is_research_stock_code(path.stem):
            continue
        try:
            stock, frame = _read_stock(path)
            if frame.empty or "ST" in str(stock.get("name") or "").upper() or len(frame) < 120:
                continue
            prepared = attach_point_in_time_quality(features(frame), cfg.data_dir, path.stem)
            date_column = "date" if "date" in prepared.columns else "trade_date"
            if date_column not in prepared.columns:
                continue
            execution_by_date: dict[str, dict[str, Any]] = {}
            execution_path = cfg.data_dir / "execution_history" / f"{path.stem}.json.gz"
            if execution_path.exists():
                with gzip.open(execution_path, "rt", encoding="utf-8") as stream:
                    execution_by_date = {
                        str(row.get("date"))[:10]: row for row in json.load(stream)
                        if isinstance(row, dict) and row.get("date")
                    }
            candidate_trades = trades(
                prepared, candidate, market_regimes, execution_by_date,
                code=path.stem, prepared=True, allow_incomplete_exit=True,
            )
            if candidate_trades.empty:
                continue
            signal_dates = candidate_trades["signal_at"].map(
                lambda index: str(prepared.at[int(index), date_column])[:10]
            )
            masked = candidate_trades[signal_dates.isin(window_set)].copy()
            if not masked.empty:
                parts.append(masked)
        except Exception:
            continue
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def backfill_forward_shadow_from_history(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    """Fill the latest 60 trading days using frozen-candidate signals on real bars."""
    cfg = cfg or CrawlerConfig()
    recommendations = _read(cfg.data_dir / "recommendations/summary.json")
    iteration = _read(cfg.data_dir / "strategy_iterations/latest.json")
    root = cfg.data_dir / "forward_shadow"
    if (root / "evaluation.json").exists():
        existing = _read(root / "evaluation.json")
        incomplete = int((existing.get("regime_counts") or {}).get("missing") or 0) > 0
        stale_protocol = str(existing.get("evaluation_protocol") or "") != SHADOW_EVALUATION_PROTOCOL
        if incomplete or existing.get("regime_coverage_complete") is False or stale_protocol:
            invalidate_incomplete_forward_shadow(cfg)
        elif _read(root / "status.json").get("status") == "evaluated":
            return {**_read(root / "status.json"), "result": "already_evaluated_immutable"}
    as_of = _resolve_as_of(cfg, recommendations)
    window = historical_shadow_window(as_of)
    snapshots = _snapshots(root)
    if not as_of or not window:
        return _status(root, snapshots, result="invalid_trade_date", trade_date=None, window=window)
    if not _iteration_frozen(iteration):
        return _status(
            root, snapshots, result="rejected_not_preregistered", trade_date=as_of, window=window
        )
    candidate = _candidate_by_name(str(iteration.get("selected_candidate") or ""))
    if candidate is None:
        return _status(
            root, snapshots, result="rejected_unknown_candidate", trade_date=as_of, window=window
        )

    market_regimes = _load_market_regimes(cfg)
    coverage = _regime_coverage(window, market_regimes)
    if candidate.allowed_regimes and not coverage["coverage_complete"]:
        return _status(
            root,
            snapshots,
            result="waiting_for_complete_market_regime",
            trade_date=as_of,
            window=window,
            extra={
                "selected_candidate": candidate.name,
                "window_trading_days": len(window),
                "missing_regime_days": coverage["missing_count"],
                "regime_counts": coverage["regime_counts"],
                "allowed_regimes": list(candidate.allowed_regimes),
            },
        )

    research_version = str(iteration.get("research_version"))
    archived = _archive_incompatible(root, window, research_version=research_version)
    snapshots = _snapshots(root)
    existing = {
        item["trade_date"]
        for item in snapshots
        if item["trade_date"] in set(window)
        and str(item.get("strategy_version") or "") == research_version
    }
    missing = [day for day in window if day not in existing]
    created_count = 0
    signals_by_date: dict[str, list[dict[str, Any]]] = {}
    if missing:
        signals_by_date = _build_historical_signals(
            cfg, candidate, window, market_regimes,
        )
        for trade_date in missing:
            payload = {
                "recorded_at": now_str(),
                "trade_date": trade_date,
                "strategy_version": research_version,
                "strategy_run_id": iteration.get("run_id"),
                "selected_candidate": candidate.name,
                "selected_horizon": candidate.horizon,
                "source": "historical_real_window",
                "source_as_of": as_of,
                "regime_coverage_complete": True,
                "signals": signals_by_date.get(trade_date) or [],
                "immutable": True,
            }
            if _write_once(root / "signals" / f"{trade_date}.json", payload):
                created_count += 1
    snapshots = _snapshots(root)
    if not signals_by_date:
        signals_by_date = {
            item["trade_date"]: item.get("signals") or []
            for item in snapshots
            if item["trade_date"] in set(window)
        }
    total_signals = sum(len(rows) for rows in signals_by_date.values())
    days_with_signals = sum(1 for rows in signals_by_date.values() if rows)
    result = "recorded" if created_count else "already_recorded_immutable"
    if archived and created_count:
        result = "backfilled_after_archive"
    elif archived and not created_count:
        result = "archived_incompatible_only"
    return _status(
        root,
        snapshots,
        result=result,
        trade_date=as_of,
        window=window,
        created=created_count > 0,
        extra={
            "created_snapshots": created_count,
            "archived_incompatible": archived,
            "selected_candidate": candidate.name,
            "window_trading_days": len(window),
            "total_signals": total_signals,
            "days_with_signals": days_with_signals,
            "allowed_regimes": list(candidate.allowed_regimes),
            "regime_coverage_complete": coverage["coverage_complete"],
            "regime_counts": coverage["regime_counts"],
        },
    )


def evaluate_forward_shadow(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    """Evaluate the filled 60-day shadow window once; never overwrite a complete verdict."""
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "forward_shadow"
    evaluation_path = root / "evaluation.json"
    if evaluation_path.exists():
        existing = _read(evaluation_path)
        incomplete = int((existing.get("regime_counts") or {}).get("missing") or 0) > 0
        stale_protocol = str(existing.get("evaluation_protocol") or "") != SHADOW_EVALUATION_PROTOCOL
        if (
            not incomplete
            and existing.get("regime_coverage_complete") is not False
            and not stale_protocol
        ):
            return {**existing, "result": "already_evaluated_immutable"}
        invalidate_incomplete_forward_shadow(cfg)

    status = _read(root / "status.json")
    iteration = _read(cfg.data_dir / "strategy_iterations/latest.json")
    if status.get("start") and status.get("end"):
        window = [
            day for day in get_calendar().fetch_dates()
            if status["start"] <= day <= status["end"]
        ]
    else:
        window_end = _iso_date(status.get("end") or status.get("last_trade_date"))
        window = historical_shadow_window(window_end) if window_end else []
    snapshots = _snapshots(root)
    recorded = int(status.get("recorded_trading_days") or len(snapshots))
    if recorded < FORWARD_SHADOW_MIN_TRADING_DAYS or len(window) < FORWARD_SHADOW_MIN_TRADING_DAYS:
        # 若信号因不完整评估被作废，尝试重建后再评。
        rebuilt = backfill_forward_shadow_from_history(cfg)
        status = rebuilt
        if status.get("start") and status.get("end"):
            window = [
                day for day in get_calendar().fetch_dates()
                if status["start"] <= day <= status["end"]
            ]
        snapshots = _snapshots(root)
        recorded = int(status.get("recorded_trading_days") or 0)
        if recorded < FORWARD_SHADOW_MIN_TRADING_DAYS or len(window) < FORWARD_SHADOW_MIN_TRADING_DAYS:
            return {
                "status": "not_ready",
                "result": "rejected_before_60_trading_days",
                "recorded_trading_days": recorded,
                "window_trading_days": len(window),
            }
    if not _iteration_frozen(iteration):
        return {"status": "not_ready", "result": "rejected_not_preregistered"}

    selected = _candidate_by_name(str(iteration.get("selected_candidate") or ""))
    if selected is None:
        return {"status": "not_ready", "result": "rejected_unknown_candidate"}
    market_regimes = _load_market_regimes(cfg)
    coverage = _regime_coverage(window, market_regimes)
    if selected.allowed_regimes and not coverage["coverage_complete"]:
        return {
            "status": "not_ready",
            "result": "rejected_incomplete_market_regime",
            "missing_regime_days": coverage["missing_count"],
            "missing_days_sample": coverage["missing_days"][:10],
            "regime_counts": coverage["regime_counts"],
            "detail": "regime 过滤候选要求影子窗口每个交易日都有市场状态；请先刷新 market_regime",
        }

    baseline_name = BASELINE_BY_HORIZON.get(selected.horizon, "baseline_long_only")
    baseline = _candidate_by_name(baseline_name) or next(
        item for item in CANDIDATES if item.name == baseline_name
    )
    selected_trades = _collect_window_trades(cfg, selected, window, market_regimes)
    baseline_trades = _collect_window_trades(cfg, baseline, window, market_regimes)
    selected_metrics = summarize([selected_trades] if not selected_trades.empty else [])
    baseline_metrics = summarize([baseline_trades] if not baseline_trades.empty else [])
    passed, fail_reasons = _shadow_promotion_passed(selected_metrics, baseline_metrics)

    ledger_signals = sum(
        len(item.get("signals") or []) for item in snapshots if item["trade_date"] in set(window)
    )
    days_with_signals = sum(
        1 for item in snapshots
        if item["trade_date"] in set(window) and (item.get("signals") or [])
    )
    if selected.allowed_regimes and not any(
        coverage["regime_counts"].get(name, 0) > 0 for name in selected.allowed_regimes
    ):
        fail_reasons = list(dict.fromkeys([*fail_reasons, "no_allowed_regime_days_in_window"]))
        passed = False

    decision = "promote_from_forward_shadow" if passed else "reject_keep_research"
    payload = {
        "status": "evaluated",
        "result": "evaluated_once",
        "evaluated_at": now_str(),
        "evaluation_locked": True,
        "immutable": True,
        "evaluation_protocol": SHADOW_EVALUATION_PROTOCOL,
        "regime_coverage_complete": coverage["coverage_complete"],
        "research_version": iteration.get("research_version"),
        "strategy_run_id": iteration.get("run_id"),
        "selected_candidate": selected.name,
        "selected_horizon": selected.horizon,
        "baseline_candidate": baseline.name,
        "window_start": window[0],
        "window_end": window[-1],
        "window_trading_days": len(window),
        "ledger_total_signals": ledger_signals,
        "ledger_days_with_signals": days_with_signals,
        "regime_counts": coverage["regime_counts"],
        "selected_metrics": selected_metrics,
        "baseline_metrics": baseline_metrics,
        "gates": {
            "minimum_trades": SHADOW_MIN_TRADES,
            "hit_rate_floor": SHADOW_HIT_RATE_FLOOR,
            "require_positive_median": True,
            "must_beat_baseline_return": True,
            "drawdown_not_worse_than_baseline": True,
            "require_complete_regime_coverage_for_regime_filtered_candidates": True,
        },
        "promotion_passed": passed,
        "fail_reasons": fail_reasons,
        "decision": decision,
        "source": "historical_real_window",
    }
    if not _write_once(evaluation_path, payload):
        return {**_read(evaluation_path), "result": "already_evaluated_immutable"}

    locked_status = {
        **status,
        "updated_at": now_str(),
        "status": "evaluated",
        "result": "evaluated_once",
        "evaluation_locked": True,
        "promotion_passed": passed,
        "decision": decision,
        "evaluation_path": "forward_shadow/evaluation.json",
        "selected_candidate": selected.name,
        "allowed_regimes": list(selected.allowed_regimes),
        "total_signals": ledger_signals,
        "days_with_signals": days_with_signals,
        "fail_reasons": fail_reasons,
        "selected_metrics": selected_metrics,
        "baseline_metrics": baseline_metrics,
        "regime_coverage_complete": coverage["coverage_complete"],
        "overwrite_forbidden": True,
    }
    (root / "status.json").write_text(
        json.dumps(locked_status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def record_forward_shadow(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    """Backfill the latest 60 real trading days, then append today's recommendation snapshot."""
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "forward_shadow"
    if (root / "evaluation.json").exists():
        existing = _read(root / "evaluation.json")
        incomplete = int((existing.get("regime_counts") or {}).get("missing") or 0) > 0
        stale_protocol = str(existing.get("evaluation_protocol") or "") != SHADOW_EVALUATION_PROTOCOL
        if incomplete or existing.get("regime_coverage_complete") is False or stale_protocol:
            invalidate_incomplete_forward_shadow(cfg)
        elif _read(root / "status.json").get("status") == "evaluated":
            return {**_read(root / "status.json"), "result": "already_evaluated_immutable"}
    status = backfill_forward_shadow_from_history(cfg)
    recommendations = _read(cfg.data_dir / "recommendations/summary.json")
    iteration = _read(cfg.data_dir / "strategy_iterations/latest.json")
    trade_date = _iso_date((recommendations.get("market_context") or {}).get("trade_date"))
    window = historical_shadow_window(status.get("end") or trade_date or status.get("requested_trade_date") or "")
    snapshots = _snapshots(root)
    if not trade_date:
        return status
    if not window:
        window = historical_shadow_window(trade_date)
    if trade_date not in set(window):
        return status
    target = root / "signals" / f"{trade_date}.json"
    if target.exists():
        return _status(
            root,
            snapshots,
            result=status.get("result") or "already_recorded_immutable",
            trade_date=trade_date,
            window=window,
            extra={
                "created_snapshots": status.get("created_snapshots", 0),
                "archived_incompatible": status.get("archived_incompatible", 0),
                "selected_candidate": status.get("selected_candidate"),
                "window_trading_days": len(window),
            },
        )
    if not _is_preregistered(iteration, trade_date) and not _iteration_frozen(iteration):
        return _status(
            root, snapshots, result="rejected_not_preregistered", trade_date=trade_date, window=window
        )
    payload = {
        "recorded_at": now_str(),
        "trade_date": trade_date,
        "strategy_version": iteration.get("research_version"),
        "strategy_run_id": iteration.get("run_id"),
        "selected_candidate": iteration.get("selected_candidate"),
        "source": "recommendations_summary",
        "source_updated_at": recommendations.get("updated_at"),
        "signals": _signals_from_recommendations(recommendations),
        "immutable": True,
    }
    created = _write_once(target, payload)
    snapshots = _snapshots(root)
    return _status(
        root,
        snapshots,
        result="recorded" if created else "already_recorded_immutable",
        trade_date=trade_date,
        window=window,
        created=created,
        extra={
            "created_snapshots": int(status.get("created_snapshots") or 0) + int(created),
            "archived_incompatible": status.get("archived_incompatible", 0),
            "selected_candidate": iteration.get("selected_candidate"),
            "window_trading_days": len(window),
        },
    )
