"""Current trend strategy and detached one-year validation worker."""

from __future__ import annotations

import json
import gzip
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.trend_development import analyze_trend_development, evaluate_history
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str


def _read_stock(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    history_path = path.parent.parent / "history" / f"{path.stem}.json.gz"
    if history_path.exists():
        with gzip.open(history_path, "rt", encoding="utf-8") as stream:
            rows = json.load(stream)
    else:
        rows = payload.get("kline") or []
    return payload, pd.DataFrame(rows)


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_trend_strategy_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    output = cfg.data_dir / "strategy"
    rows: list[dict[str, Any]] = []
    for path in sorted((cfg.data_dir / "stocks").glob("*.json")):
        if path.stem == "index" or not is_research_stock_code(path.stem):
            continue
        try:
            stock, frame = _read_stock(path)
            if "ST" in str(stock.get("name") or "").upper():
                continue
            result = analyze_trend_development(frame, path.stem, str(stock.get("name") or ""))
            _write(output / path.name, result)
            rows.append({key: result.get(key) for key in ("code", "name", "trade_date", "status", "trend_stage", "trend_score", "confidence")})
        except Exception:
            continue
    index = {"updated_at": now_str(), "strategy": "trend_development", "count": len(rows), "items": rows}
    _write(output / "index.json", index)
    return index


def validation_calibration(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Expose one-year validation through the existing calibration contract during migration."""
    if not payload:
        return None
    metrics = payload.get("metrics") or {}
    primary = metrics.get("20d") or metrics.get("5d") or {}
    if not primary.get("sample_count"):
        return None
    return {
        "replay_version": "trend_development_5y",
        "status": "evaluated",
        "window_days": int(payload.get("evaluated_window_days") or payload.get("requested_window_days") or 252),
        "summary": {
            "evaluated_count": primary.get("sample_count"),
            "step_count": primary.get("sample_count"),
            "hit_rate": primary.get("hit_rate"),
            "avg_return_pct": primary.get("avg_signed_return_pct"),
        },
        "limitations": payload.get("limitations") or [],
    }


def run_offline_five_year_validation() -> dict[str, Any]:
    cfg = CrawlerConfig()
    root = cfg.data_dir / "strategy_backtest"
    status_path = root / "status.json"
    paths = [
        p for p in sorted((cfg.data_dir / "stocks").glob("*.json"))
        if p.stem != "index" and is_research_stock_code(p.stem)
    ]
    _write(status_path, {"status": "running", "started_at": now_str(), "total": len(paths), "completed": 0})
    rows: list[dict[str, Any]] = []
    for index, path in enumerate(paths, 1):
        try:
            stock, frame = _read_stock(path)
            if "ST" in str(stock.get("name") or "").upper() or len(frame) < 120:
                continue
            validation = evaluate_history(frame, window_days=cfg.research_hist_days)
            payload = {"code": path.stem, "name": stock.get("name"), "strategy": "trend_development", "strategy_version": "1.1.0", "validation_version": "five_year_1250d", "updated_at": now_str(), **validation}
            _write(root / path.name, payload)
            rows.append({"code": path.stem, "name": stock.get("name"), **validation["metrics"]})
        except Exception:
            pass
        if index % 50 == 0:
            _write(status_path, {"status": "running", "started_at": None, "updated_at": now_str(), "total": len(paths), "completed": index})
    summary = {"status": "complete", "updated_at": now_str(), "total": len(paths), "completed": len(paths), "validated": len(rows), "items": rows}
    _write(root / "index.json", summary)
    _write(status_path, summary | {"items": []})
    return summary


def run_offline_one_year_validation() -> dict[str, Any]:
    """Compatibility entrypoint; active validation policy is now five years."""
    return run_offline_five_year_validation()


def launch_offline_validation() -> dict[str, Any]:
    cfg = CrawlerConfig()
    root = cfg.data_dir / "strategy_backtest"
    pid_path = root / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pass
    root.mkdir(parents=True, exist_ok=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.strategy_job", "--offline"],
        cwd=str(Path(__file__).resolve().parents[2]), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "started", "pid": process.pid}


if __name__ == "__main__" and "--offline" in sys.argv:
    try:
        run_offline_five_year_validation()
    finally:
        (CrawlerConfig().data_dir / "strategy_backtest" / "worker.pid").unlink(missing_ok=True)
