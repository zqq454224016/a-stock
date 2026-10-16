"""Long-running dependency-aware iteration worker."""

from __future__ import annotations

import json
import fcntl
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from quant_system.ai.data_acquisition_advisor import (
    acquisition_evidence,
    evidence_fingerprint,
    generate_data_acquisition_advice,
)
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.iteration.auto_iteration import run_auto_iteration
from quant_system.tasks.recommendation_job import run_recommendation_job
from quant_system.tasks.strategy_job import launch_offline_validation, run_trend_strategy_job
from quant_system.tasks.strategy_iteration_job import RESEARCH_VERSION, run_strategy_iteration
from quant_system.tasks.market_regime_job import MARKET_REGIME_VERSION, run_market_regime_job
from quant_system.tasks.interim_financial_job import (
    _period,
    launch_public_financial_backfill,
    run_interim_financial_job,
)
from quant_system.tasks.execution_data_job import launch_execution_data_job, run_execution_feature_build
from quant_system.tasks.market_event_job import run_market_event_job
from quant_system.tasks.st_event_job import run_st_event_job
from quant_system.tasks.sse_event_job import run_sse_event_job
from quant_system.tasks.today_change_job import run_today_change_job
from quant_system.tasks.daily_market_recap_job import run_daily_market_recap_job
from quant_system.tasks.sector_data_job import SECTOR_DATA_VERSION, launch_sector_data_job
from quant_system.strategy.forward_shadow import evaluate_forward_shadow, record_forward_shadow
from quant_system.tasks.full_acquisition_job import launch_full_acquisition
from quant_system.tasks.public_quote_merge_job import run_public_quote_merge
from quant_system.tasks.us_cpi_job import run_us_cpi_job
from quant_system.tasks.public_supplement_job import run_public_supplement_job
from quant_system.tasks.polarized_strategy_job import run_polarized_strategy
from quant_system.tasks.overnight_iteration_job import run_overnight_iteration
from quant_system.tasks.aggressive_board_iteration_job import run_aggressive_board_iteration
from quant_system.tasks.horizon_strategy_analysis_job import run_horizon_strategy_analysis
from quant_system.utils.time_utils import now_str
from quant_system.notifications.feishu import notify_iteration_progress
from quant_system.iteration.eta import build_iteration_eta
from quant_system.utils.trade_calendar import get_calendar


@dataclass(frozen=True)
class WorkerConfig:
    # Continuously observe dependency fingerprints. Heavy jobs still run only when
    # their upstream data changes, so a short poll interval does not repeat backtests.
    interval_sec: int = max(300, int(os.getenv("AUTO_ITERATION_INTERVAL_SEC", "300")))
    ai_cooldown_sec: int = 0
    ai_enabled: bool = os.getenv("AUTO_ITERATION_AI", "1") != "0"


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


def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def _newer_than(target: Path, dependencies: list[Path]) -> bool:
    target_time = _mtime(target)
    return target_time == 0 or any(_mtime(path) > target_time for path in dependencies)


def _ai_advice_due(cfg: CrawlerConfig, worker_cfg: WorkerConfig) -> bool:
    if not worker_cfg.ai_enabled:
        return False
    metadata = _read(cfg.data_dir / "iteration/data_acquisition_advice.json")
    fingerprint = evidence_fingerprint(acquisition_evidence(cfg))
    if metadata.get("fingerprint") == fingerprint and metadata.get("status") in {"complete", "rejected", "failed"}:
        return False
    return True


def _public_financial_due(cfg: CrawlerConfig) -> bool:
    status = _read(cfg.data_dir / "point_in_time_financials/status.json")
    return status.get("period") != f"{_period()[:4]}-{_period()[4:6]}-{_period()[6:]}" or status.get("as_of") != datetime.now().date().isoformat()


def _full_acquisition_due(cfg: CrawlerConfig) -> bool:
    """Refresh once per target trading session; file existence alone is not freshness."""
    try:
        target = _latest_completed_trade_day()
    except Exception:
        return False
    status = _read(cfg.data_dir / "acquisition/status.json")
    if status.get("status") in {"starting", "running"} and status.get("target_trade_date") == target:
        return False
    stock_index = _read(cfg.data_dir / "stocks/index.json")
    return str(stock_index.get("trade_date") or "") < target


def _latest_completed_trade_day() -> str:
    return get_calendar().latest_completed_trade_day(datetime.now())


def _strategy_iteration_due(cfg: CrawlerConfig, latest_path: Path, dependencies: list[Path]) -> bool:
    latest = _read(latest_path)
    return latest.get("research_version") != RESEARCH_VERSION or _newer_than(latest_path, dependencies)


def _sector_data_due(cfg: CrawlerConfig, sector_status: Path, stock_index: Path) -> bool:
    state = _read(sector_status)
    if state.get("version") != SECTOR_DATA_VERSION or state.get("status") != "complete":
        return True
    stock = _read(stock_index)
    target_date = str(stock.get("trade_date") or "")[:10]
    if not target_date:
        today = _read(cfg.data_dir / "today_change/summary.json")
        target_date = str(today.get("trade_date") or "")[:10]
    rotation = _read(cfg.data_dir / "sector_data/rotation.json")
    rot_date = str(rotation.get("trade_date") or state.get("latest_trade_date") or "")[:10]
    if not target_date or not rot_date or rot_date < target_date:
        # 行业指数源可能比个股晚一天；同一交易日已完整拉取过则不再空转刷接口。
        attempted = str(state.get("attempted_trade_date") or "")[:10]
        if attempted == target_date and state.get("status") == "complete":
            return False
        return bool(target_date)
    return False


def _market_regime_due(cfg: CrawlerConfig, path: Path, stock_index: Path) -> bool:
    payload = _read(path)
    if payload.get("version") != MARKET_REGIME_VERSION or _newer_than(path, [stock_index]):
        return True
    # 内容新鲜度：仅看文件 mtime 会漏掉「股票已更新但 regime 未重建」的情况。
    stock = _read(stock_index)
    target_date = str(stock.get("trade_date") or "")[:10]
    if not target_date:
        today = _read(cfg.data_dir / "today_change/summary.json")
        target_date = str(today.get("trade_date") or "")[:10]
    latest_regime = str(payload.get("latest_trade_date") or "")[:10]
    if not latest_regime:
        items = payload.get("items") or []
        if items:
            latest_regime = str(items[-1].get("date") or "")[:10]
    return bool(target_date and (not latest_regime or latest_regime < target_date))


def _strategy_waiting_state(cfg: CrawlerConfig, actions: list[dict[str, Any]]) -> dict[str, Any]:
    latest = _read(cfg.data_dir / "strategy_iterations/latest.json")
    ran = any(row.get("name") == "robust_strategy_iteration" for row in actions)
    if ran:
        state = "evaluated_this_round"
        reason = "研究输入或研究版本发生变化"
    elif latest.get("promotion_passed"):
        state = "passed_waiting_human_promotion"
        reason = "硬门禁已通过，是否启用影子策略必须人工确认"
    else:
        state = "waiting_for_new_oos_or_preregistered_research_version"
        reason = "当前冻结样本外已使用；禁止在同一OOS上继续自动调参"
    return {
        "state": state,
        "reason": reason,
        "latest_run_id": latest.get("run_id"),
        "research_version": latest.get("research_version"),
        "latest_decision": latest.get("decision"),
        "next_automatic_trigger": "new_completed_trading_day_or_research_version_change",
    }


def _validate_freshness(cfg: CrawlerConfig) -> dict[str, Any]:
    """统一交易日校验；不一致时保留 invalidated 标记，下一轮继续补数。"""
    paths = {
        "stock": cfg.data_dir / "today_change/summary.json",
        "sector": cfg.data_dir / "sector_data/rotation.json",
        "index": cfg.data_dir / "latest.json",
    }
    dates = {}
    for name, path in paths.items():
        payload = _read(path)
        value = payload.get("trade_date")
        if value:
            dates[name] = str(value)
    reset = cfg.data_dir / "data_freshness/reset.json"
    stable = len(dates) == 3 and len(set(dates.values())) == 1
    if stable:
        reset.unlink(missing_ok=True)
    else:
        _write(reset, {"status": "invalidated", "reason": "核心行情交易日不一致，后台持续补数", "dates": dates, "updated_at": now_str(), "allow_formal_recommendation": False})
    return {"stable": stable, "dates": dates, "status": "valid" if stable else "invalidated"}


def run_iteration_round(
    cfg: CrawlerConfig | None = None,
    worker_cfg: WorkerConfig | None = None,
    *,
    advisor: Callable[..., dict[str, Any]] = generate_data_acquisition_advice,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    worker_cfg = worker_cfg or WorkerConfig()
    root = cfg.data_dir / "iteration"
    actions: list[dict[str, Any]] = []
    _write(root / "worker_status.json", {
        "updated_at": now_str(),
        "status": "running_round",
        "pid": os.getpid(),
        "interval_sec": worker_cfg.interval_sec,
        "ai_scope": "data_acquisition_methods_only",
        "actions": [],
    })

    def action_result(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
        try:
            result = fn()
            return {"name": name, "status": "success", "result_status": result.get("status") if isinstance(result, dict) else None}
        except Exception as exc:  # noqa: BLE001
            return {"name": name, "status": "failed", "error": str(exc)[-500:]}

    def execute(name: str, fn: Callable[[], Any]) -> None:
        actions.append(action_result(name, fn))

    stock_index = cfg.data_dir / "stocks/index.json"
    market = cfg.data_dir / "latest.json"
    strategy_index = cfg.data_dir / "strategy/index.json"
    today_summary = cfg.data_dir / "today_change/summary.json"
    daily_recap = cfg.data_dir / "daily_market_recap/latest.json"
    validation_index = cfg.data_dir / "strategy_backtest/index.json"
    robust_iteration = cfg.data_dir / "strategy_iterations/latest.json"
    market_regime = cfg.data_dir / "market_regime/five_year.json"
    raw_history_status = cfg.data_dir / "raw_history/status.json"
    market_event_status = cfg.data_dir / "market_events/status.json"
    st_change_status = cfg.data_dir / "market_events/st_changes_sz.json"
    sse_event_status = cfg.data_dir / "market_events/sse/status.json"
    execution_status = cfg.data_dir / "execution_history/status.json"
    recommendations = cfg.data_dir / "recommendations/summary.json"
    financial_status = cfg.data_dir / "point_in_time_financials/status.json"
    sector_status = cfg.data_dir / "sector_data/status.json"
    cpi_path = cfg.data_dir / "macro/us_cpi.json"
    if _mtime(cpi_path) == 0 or datetime.now().date().isoformat() not in str(_read(cpi_path).get("updated_at", "")):
        execute("us_cpi", lambda: run_us_cpi_job(cfg.data_dir))

    if _full_acquisition_due(cfg):
        target_trade_date = _latest_completed_trade_day()
        public_snapshot = _read(cfg.data_dir / "normalized/market.quotes.tencent/latest.json")
        if str(public_snapshot.get("trade_date") or "") < target_trade_date:
            execute("public_market_snapshot_refresh", run_public_supplement_job)
        merge_result = action_result(
            "public_quote_history_merge",
            lambda: run_public_quote_merge(cfg, target_trade_date),
        )
        actions.append(merge_result)
        if merge_result.get("result_status") not in {"complete", "partial"}:
            execute("full_market_data_refresh", launch_full_acquisition)

    independent: list[tuple[str, Callable[[], Any]]] = []
    if _newer_than(today_summary, [stock_index, market]):
        independent.append(("today_change", run_today_change_job))
    if _newer_than(strategy_index, [stock_index]):
        independent.append(("trend_strategy", run_trend_strategy_job))
    if len(independent) > 1:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="iteration") as pool:
            futures = [(name, pool.submit(action_result, name, fn)) for name, fn in independent]
            actions.extend(future.result() for _name, future in futures)
    elif independent:
        execute(*independent[0])
    if _newer_than(daily_recap, [today_summary, sector_status, cfg.data_dir / "normalized/market.limit_pool.sentiment/latest.json"]):
        execute("daily_market_recap", run_daily_market_recap_job)
    if _newer_than(validation_index, [strategy_index]):
        execute("offline_validation", launch_offline_validation)
    if _public_financial_due(cfg):
        execute("point_in_time_financials", run_interim_financial_job)
    if _sector_data_due(cfg, sector_status, stock_index):
        execute("sector_data", lambda: launch_sector_data_job(cfg))
    financial_backfill = _read(cfg.data_dir / "point_in_time_financials/backfill_status.json")
    if financial_backfill.get("status") != "complete":
        execute("point_in_time_financial_backfill", lambda: launch_public_financial_backfill(cfg))
    if _newer_than(recommendations, [strategy_index, today_summary, validation_index, financial_status, sector_status]):
        execute("recommendations", run_recommendation_job)
    # 极化实验候选与正式推荐解耦，但每轮数据更新后必须同步刷新。
    if _newer_than(cfg.data_dir / "strategy_iterations/polarized_latest.json", [strategy_index, today_summary, sector_status, market_regime]):
        execute("polarized_strategy", run_polarized_strategy)
    # 市场状态必须先于前向影子/锦标赛：regime 过滤候选依赖完整交易日覆盖。
    if _market_regime_due(cfg, market_regime, stock_index):
        execute("market_regime", lambda: run_market_regime_job(cfg))
    execute("forward_shadow_snapshot", lambda: record_forward_shadow(cfg))
    shadow_status = _read(cfg.data_dir / "forward_shadow/status.json")
    if (
        shadow_status.get("status") == "evaluation_due"
        and int(shadow_status.get("recorded_trading_days") or 0) >= 60
        and not (cfg.data_dir / "forward_shadow/evaluation.json").exists()
    ):
        execute("forward_shadow_evaluation", lambda: evaluate_forward_shadow(cfg))
    raw_status = _read(raw_history_status)
    if raw_status.get("status") != "complete":
        execute("execution_data_backfill", lambda: launch_execution_data_job(cfg))
    else:
        execute("st_events_sz", lambda: run_st_event_job(cfg))
        execute("st_events_sh", lambda: run_sse_event_job(cfg))
        if _newer_than(market_event_status, [cfg.data_dir / "market_regime/five_year.json", st_change_status, sse_event_status]):
            execute("market_events", lambda: run_market_event_job(cfg))
        if _newer_than(execution_status, [raw_history_status, market_event_status, st_change_status, sse_event_status]):
            execute("execution_constraints", lambda: run_execution_feature_build(cfg))
    if _strategy_iteration_due(
        cfg, robust_iteration,
        [stock_index, market_regime, execution_status, market_event_status],
    ):
        execute("robust_strategy_iteration", lambda: run_strategy_iteration(cfg))
    overnight_latest = cfg.data_dir / "overnight_iterations/latest.json"
    if _newer_than(overnight_latest, [stock_index, market_regime, execution_status]):
        execute("overnight_parallel_tournament", lambda: run_overnight_iteration(cfg))
    aggressive_latest = cfg.data_dir / "aggressive_board_iterations/latest.json"
    if _newer_than(aggressive_latest, [stock_index, market_regime, execution_status]):
        execute("aggressive_board_parallel_tournament", lambda: run_aggressive_board_iteration(cfg))
    horizon_latest = cfg.data_dir / "horizon_analysis/latest.json"
    if _newer_than(
        horizon_latest,
        [
            robust_iteration,
            overnight_latest,
            aggressive_latest,
            cfg.data_dir / "recommendations/summary.json",
        ],
    ):
        execute("horizon_strategy_analysis", lambda: run_horizon_strategy_analysis(cfg))
    execute("iteration_audit", lambda: run_auto_iteration(cfg))
    freshness = _validate_freshness(cfg)
    actions.append({"name": "data_freshness_validation", "status": "success", "result_status": freshness["status"], "dates": freshness["dates"]})
    if _ai_advice_due(cfg, worker_cfg):
        execute("ai_data_acquisition_advice", lambda: advisor(cfg))
        if actions[-1]["status"] == "failed":
            _write(root / "data_acquisition_advice.json", {
                "updated_at": now_str(),
                "fingerprint": evidence_fingerprint(acquisition_evidence(cfg)),
                "status": "failed",
                "scope": "data_acquisition_methods_only",
                "error": actions[-1].get("error"),
            })

    payload = {
        "updated_at": now_str(),
        "status": "round_complete",
        "pid": os.getpid(),
        "interval_sec": worker_cfg.interval_sec,
        "ai_scope": "data_acquisition_methods_only",
        "execution_mode": "dependency_graph_parallel",
        "actions": actions,
        "strategy_iteration_state": _strategy_waiting_state(cfg, actions),
        "next_run_after": datetime.fromtimestamp(time.time() + worker_cfg.interval_sec).strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload["eta"] = build_iteration_eta(
        cfg, next_run_after=payload["next_run_after"],
    )
    _write(root / "worker_status.json", payload)
    # 飞书仅在本轮结束后同步；周期内心跳不再刷屏。
    payload["notification"] = notify_iteration_progress(payload, data_dir=cfg.data_dir)
    _write(root / "worker_status.json", payload)
    return payload


def run_worker_forever() -> None:
    cfg = CrawlerConfig()
    worker_cfg = WorkerConfig()
    root = cfg.data_dir / "iteration"
    root.mkdir(parents=True, exist_ok=True)
    lock_stream = (root / "worker.lock").open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    stop_path = root / "worker.stop"
    try:
        while not stop_path.exists():
            # 自动迭代只在收盘后启动，避免盘中半成品行情触发策略和消耗额度。
            now = datetime.now()
            if now.hour < 15:
                wait = max(30, int((datetime.combine(now.date(), datetime.min.time()).timestamp() + 15 * 3600) - now.timestamp()))
                _write(root / "worker_status.json", {"updated_at": now_str(), "status": "waiting_after_close", "pid": os.getpid(), "next_run_after": datetime.fromtimestamp(now.timestamp() + wait).strftime("%Y-%m-%d %H:%M:%S"), "interval_sec": worker_cfg.interval_sec, "ai_scope": "data_acquisition_methods_only"})
                time.sleep(min(wait, 300))
                continue
            run_iteration_round(cfg, worker_cfg)
            for _ in range(max(1, worker_cfg.interval_sec // 30)):
                if stop_path.exists():
                    break
                time.sleep(min(30, worker_cfg.interval_sec))
        _write(root / "worker_status.json", {"updated_at": now_str(), "status": "stopped", "pid": os.getpid()})
    finally:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()


def launch_iteration_worker(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "iteration"
    root.mkdir(parents=True, exist_ok=True)
    pid_path = root / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            # PID 存在但状态文件长期不更新时视为僵尸 worker，允许自动重启。
            status_path = root / "worker_status.json"
            stale = status_path.exists() and (time.time() - status_path.stat().st_mtime > 1800)
            if not stale:
                return {"status": "already_running", "pid": pid}
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    (root / "worker.stop").unlink(missing_ok=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.iteration.worker", "--daemon"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    _write(root / "worker_status.json", {
        "updated_at": now_str(),
        "status": "starting",
        "pid": process.pid,
        "interval_sec": WorkerConfig().interval_sec,
        "ai_scope": "data_acquisition_methods_only",
        "actions": [],
    })
    started = {"status": "started", "pid": process.pid}
    notify_iteration_progress({
        "updated_at": now_str(), "status": "worker_started", "actions": [],
        "next_run_after": "后台启动后立即执行",
    }, force=True, data_dir=cfg.data_dir)
    return started


if __name__ == "__main__" and "--daemon" in sys.argv:
    try:
        run_worker_forever()
    finally:
        (CrawlerConfig().data_dir / "iteration/worker.pid").unlink(missing_ok=True)
