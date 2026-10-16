"""Resumable detached acquisition of the complete research universe."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import fcntl
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.tasks.strategy_job import launch_offline_validation, run_trend_strategy_job
from quant_system.tasks.today_change_job import run_today_change_job
from quant_system.tasks.recommendation_job import run_recommendation_job
from quant_system.tasks.universe_job import load_tickflow_universe, sync_tickflow_universe
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_full_acquisition() -> dict[str, Any]:
    cfg = CrawlerConfig()
    root = cfg.data_dir / "acquisition"
    status_path = root / "status.json"
    stocks = filter_research_stocks(
        load_tickflow_universe(cfg) or sync_tickflow_universe(cfg),
        cfg,
        reason="全量研究历史",
    )
    previous: dict[str, Any] = {}
    if status_path.exists():
        try:
            previous = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    target_trade_date = get_calendar().latest_completed_trade_day()
    same_target = (
        previous.get("target_days") == cfg.research_hist_days
        and previous.get("target_trade_date") == target_trade_date
    )
    completed = set(previous.get("completed_codes") or []) if same_target else set()
    universe_codes = {str(item.get("code")) for item in stocks}
    completed.intersection_update(universe_codes)
    pending = [item for item in stocks if str(item.get("code")) not in completed]
    started_at = previous.get("started_at") or now_str()
    chunk_size = max(1, min(int(cfg.tickflow_batch_size), 200))

    for start in range(0, len(pending), chunk_size):
        chunk = pending[start:start + chunk_size]
        rows = run_daily_stock(items=chunk, batch_history=True)
        completed.update(str(row["code"]) for row in rows)
        _write(status_path, {
            "status": "running",
            "started_at": started_at,
            "updated_at": now_str(),
            "target_days": cfg.research_hist_days,
            "target_trade_date": target_trade_date,
            "total": len(stocks),
            "completed": len(completed),
            "failed_or_pending": len(stocks) - len(completed),
            "progress_pct": round(len(completed) / max(1, len(stocks)) * 100, 2),
            "completed_codes": sorted(completed),
        })

    status = "complete" if len(completed) >= len(stocks) else "partial"
    payload = {
        "status": status,
        "started_at": started_at,
        "updated_at": now_str(),
        "target_days": cfg.research_hist_days,
        "target_trade_date": target_trade_date,
        "total": len(stocks),
        "completed": len(completed),
        "failed_or_pending": len(stocks) - len(completed),
        "progress_pct": round(len(completed) / max(1, len(stocks)) * 100, 2),
        "completed_codes": sorted(completed),
    }
    _write(status_path, payload)

    # 免费历史端点可能落后一个已收盘交易日。所有 TickFlow 历史写入完成后，
    # 再用已落盘的腾讯收盘快照统一补齐，避免先合并后被历史回填覆盖。
    from quant_system.tasks.public_quote_merge_job import run_public_quote_merge
    quote_merge = run_public_quote_merge(cfg, target_trade_date)
    payload["public_quote_merge_status"] = quote_merge.get("status")
    payload["public_quote_merge_trade_date"] = quote_merge.get("trade_date")
    _write(status_path, payload)

    # All downstream work is local; strategy and today's move can be computed together.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="local-compute") as pool:
        futures = [pool.submit(run_today_change_job), pool.submit(run_trend_strategy_job)]
        for future in futures:
            future.result()
    run_recommendation_job()
    launch_offline_validation()
    return payload


def launch_full_acquisition() -> dict[str, Any]:
    cfg = CrawlerConfig()
    root = cfg.data_dir / "acquisition"
    root.mkdir(parents=True, exist_ok=True)
    pid_path = root / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.full_acquisition_job", "--daemon"],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    _write(root / "status.json", {
        "status": "starting",
        "updated_at": now_str(),
        "target_days": cfg.research_hist_days,
        "target_trade_date": get_calendar().latest_trade_day(),
        "pid": process.pid,
    })
    return {"status": "started", "pid": process.pid, "target_days": cfg.research_hist_days}


if __name__ == "__main__" and "--daemon" in sys.argv:
    acquisition_root = CrawlerConfig().data_dir / "acquisition"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    lock_stream = (acquisition_root / "worker.lock").open("a+")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(0)
    try:
        run_full_acquisition()
    finally:
        pid_path = acquisition_root / "worker.pid"
        try:
            if int(pid_path.read_text().strip()) == os.getpid():
                pid_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
