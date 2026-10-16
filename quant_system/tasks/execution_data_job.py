"""Incrementally acquire raw prices and derive execution constraints locally."""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import fcntl
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.tickflow_api import TickFlowAPI
from quant_system.tasks.strategy_job import _write
from quant_system.utils.market_scope import is_additional_permission_board_code
from quant_system.utils.time_utils import now_str


def _gzip_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(path)


def _gzip_read(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, list) else []


def _limit_price(value: float, ratio: float) -> float:
    return float((Decimal(str(value)) * Decimal(str(ratio))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def run_raw_price_backfill(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    codes = [
        path.stem for path in sorted((cfg.data_dir / "stocks").glob("*.json"))
        if path.stem != "index" and not is_additional_permission_board_code(path.stem)
    ]
    root = cfg.data_dir / "raw_history"
    pending = [code for code in codes if not (root / f"{code}.json.gz").exists()]
    _write(root / "status.json", {"status": "running", "updated_at": now_str(), "total": len(codes), "completed": len(codes) - len(pending), "pending": len(pending)})
    api = TickFlowAPI(cfg)
    completed = len(codes) - len(pending)
    errors: dict[str, str] = {}
    size = max(1, min(cfg.tickflow_batch_size, 100))
    for start in range(0, len(pending), size):
        chunk = pending[start:start + size]
        try:
            frames = api.fetch_daily_hist_batch(chunk, adjust="none")
            for code in chunk:
                frame, _source = frames.get(code, (None, None))
                if frame is None or frame.empty:
                    errors[code] = "empty"
                    continue
                rows = json.loads(frame.where(frame.notna(), None).to_json(orient="records", force_ascii=False))
                _gzip_write(root / f"{code}.json.gz", rows)
                completed += 1
        except Exception as exc:  # noqa: BLE001
            for code in chunk:
                errors[code] = str(exc)[-200:]
        _write(root / "status.json", {
            "status": "running", "updated_at": now_str(), "total": len(codes),
            "completed": completed, "pending": len(codes) - completed, "error_count": len(errors),
        })
    payload = {
        "status": "complete" if completed == len(codes) else "partial",
        "updated_at": now_str(), "source": "tickflow_free_unadjusted_daily",
        "total": len(codes), "completed": completed, "pending": len(codes) - completed,
        "error_count": len(errors), "errors": dict(list(errors.items())[:20]),
    }
    _write(root / "status.json", payload)
    return payload


def run_execution_feature_build(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    raw_root, adjusted_root = cfg.data_dir / "raw_history", cfg.data_dir / "history"
    output = cfg.data_dir / "execution_history"
    try:
        st_payload = json.loads((cfg.data_dir / "market_events/st_changes_sz.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st_payload = {}
    st_by_code: dict[str, list[dict[str, Any]]] = {}
    for event in st_payload.get("events") or []:
        st_by_code.setdefault(str(event.get("code") or ""), []).append(event)
    for values in st_by_code.values():
        values.sort(key=lambda item: str(item.get("date") or ""))
    try:
        sse_payload = json.loads((cfg.data_dir / "market_events/sse/events.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sse_payload = {}
    for event in sse_payload.get("events") or []:
        st_by_code.setdefault(str(event.get("code") or ""), []).append(event)
    for values in st_by_code.values():
        values.sort(key=lambda item: str(item.get("date") or ""))
    completed = events = locked_up = locked_down = 0
    for raw_path in sorted(raw_root.glob("*.json.gz")):
        code = raw_path.name.split(".", 1)[0]
        adjusted_path = adjusted_root / f"{code}.json.gz"
        if not adjusted_path.exists():
            continue
        try:
            raw = {str(row.get("date") or row.get("trade_date"))[:10]: row for row in _gzip_read(raw_path)}
            adjusted = {str(row.get("date") or row.get("trade_date"))[:10]: row for row in _gzip_read(adjusted_path)}
            rows: list[dict[str, Any]] = []
            previous_raw_close: float | None = None
            previous_adjusted_close: float | None = None
            previous_ratio: float | None = None
            st_events = st_by_code.get(code) or []
            st_index = 0
            st_state = bool(st_events and st_events[0].get("state") == "st_end")
            for date in sorted(raw.keys() & adjusted.keys()):
                raw_row, adj_row = raw[date], adjusted[date]
                raw_close, adj_close = float(raw_row.get("close") or 0), float(adj_row.get("close") or 0)
                if raw_close <= 0 or adj_close <= 0:
                    continue
                ratio = adj_close / raw_close
                corporate_action = previous_ratio is not None and abs(ratio - previous_ratio) > 1e-6
                reference = previous_adjusted_close / ratio if corporate_action and ratio and previous_adjusted_close else previous_raw_close
                while st_index < len(st_events) and str(st_events[st_index].get("date") or "") <= date:
                    st_state = st_events[st_index].get("state") == "st_start"
                    st_index += 1
                st_known = bool(st_events)
                limit_ratio = .05 if st_known and st_state else .10
                limit_up = _limit_price(reference, 1 + limit_ratio) if reference else None
                limit_down = _limit_price(reference, 1 - limit_ratio) if reference else None
                open_, high, low = (float(raw_row.get(key) or 0) for key in ("open", "high", "low"))
                one_up = bool(limit_up and min(open_, high, low, raw_close) >= limit_up - .005)
                one_down = bool(limit_down and max(open_, high, low, raw_close) <= limit_down + .005)
                events += int(corporate_action)
                locked_up += int(one_up)
                locked_down += int(one_down)
                rows.append({
                    "date": date, "raw_open": open_, "raw_high": high, "raw_low": low,
                    "raw_close": raw_close, "adjustment_ratio": round(ratio, 10),
                    "corporate_action_inferred": corporate_action,
                    "limit_up": limit_up, "limit_down": limit_down,
                    "one_price_limit_up": one_up, "one_price_limit_down": one_down,
                    "suspended": float(raw_row.get("volume") or 0) <= 0,
                    "st_status_known": st_known, "is_st": st_state if st_known else None,
                })
                previous_raw_close, previous_adjusted_close, previous_ratio = raw_close, adj_close, ratio
            _gzip_write(output / f"{code}.json.gz", rows)
            completed += 1
        except (OSError, ValueError, TypeError):
            continue
    payload = {
        "status": "complete" if completed else "insufficient", "updated_at": now_str(),
        "stocks": completed, "corporate_action_events_inferred": events,
        "one_price_limit_up_days": locked_up, "one_price_limit_down_days": locked_down,
        "limitations": ["沪深历史ST按公开简称变更与官方公告恢复", "数据源删除的停牌日由market_events交易日历差集恢复"],
    }
    _write(output / "status.json", payload)
    return payload


def run_execution_data_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    acquisition = run_raw_price_backfill(cfg)
    build = run_execution_feature_build(cfg)
    return {"status": "complete" if acquisition["status"] == build["status"] == "complete" else "partial", "acquisition": acquisition, "build": build}


def launch_execution_data_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    root = cfg.data_dir / "raw_history"
    pid_path = root / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    log = (root / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.execution_data_job", "--offline"],
        cwd=str(Path(__file__).resolve().parents[2]), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "started", "pid": process.pid}


if __name__ == "__main__" and "--offline" in sys.argv:
    execution_root = CrawlerConfig().data_dir / "raw_history"
    execution_root.mkdir(parents=True, exist_ok=True)
    lock_stream = (execution_root / "worker.lock").open("a+")
    try:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(0)
    try:
        run_execution_data_job()
    finally:
        pid_path = execution_root / "worker.pid"
        try:
            if int(pid_path.read_text().strip()) == os.getpid():
                pid_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
        lock_stream.close()
