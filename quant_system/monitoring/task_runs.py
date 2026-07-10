"""运行时任务日志。"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quant_system.storage.json_store import JsonStore
from quant_system.utils.time_utils import now_str

TASK_RUN_VERSION = "1.0.0"
MAX_INDEX_RUNS = 100

ARTIFACT_HINTS = {
    "market": ["latest.json"],
    "stock": ["stocks/index.json", "stocks/live/index.json"],
    "factor": ["factors/index.json"],
    "factor-eval": ["factor_eval/summary.json"],
    "inspect": ["quality/latest.json"],
    "backtest": ["backtest/index.json"],
    "predict": ["predictions/index.json"],
    "selector": ["selector/index.json"],
    "decision": ["decisions/index.json"],
    "simtrade": ["trading/index.json"],
    "portfolio": ["portfolio/summary.json"],
    "review": ["review/index.json"],
    "replay": ["replay/index.json"],
    "impact": ["impact/index.json"],
    "attribution": ["attribution/index.json", "../../reports/attribution/index.html"],
    "agent": ["agent/index.json"],
    "recommend": ["recommendations/summary.json"],
    "framework": ["framework/snapshot.json"],
    "console": ["../../reports/console/index.html"],
    "monitor": ["monitoring/snapshot.json", "../../reports/monitoring/index.html"],
    "registry": ["data_registry/index.json"],
    "v3-plan": ["planning/v3_roadmap.json", "../../reports/planning/v3.html"],
}


def _slug_time(dt: datetime) -> str:
    return dt.strftime("%Y%m%d_%H%M%S_%f")


def _resolve_artifact(store: JsonStore, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    return (store.config.json_data_dir / path).resolve()


def _artifact_state(store: JsonStore, command: str) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for rel in ARTIFACT_HINTS.get(command, []):
        path = _resolve_artifact(store, rel)
        states.append({
            "path": rel,
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() and path.is_file() else None,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if path.exists() else "",
        })
    return states


@dataclass(slots=True)
class TaskRunRecorder:
    command: str
    argv: list[str]
    store: JsonStore = field(default_factory=JsonStore)
    run_id: str = ""
    started_at: str = ""
    _start_dt: datetime | None = None

    def start(self) -> None:
        self._start_dt = datetime.now()
        self.started_at = now_str()
        self.run_id = f"{_slug_time(self._start_dt)}_{self.command or 'help'}"

    def finish(self, status: str = "success", error: BaseException | None = None) -> dict[str, Any]:
        end_dt = datetime.now()
        start_dt = self._start_dt or end_dt
        payload: dict[str, Any] = {
            "task_run_version": TASK_RUN_VERSION,
            "run_id": self.run_id or f"{_slug_time(start_dt)}_{self.command or 'help'}",
            "command": self.command or "help",
            "argv": self.argv,
            "status": status,
            "started_at": self.started_at or start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": round((end_dt - start_dt).total_seconds(), 4),
            "artifacts": _artifact_state(self.store, self.command or ""),
        }
        if error is not None:
            payload["error"] = {
                "type": error.__class__.__name__,
                "message": str(error),
                "traceback": traceback.format_exception_only(error.__class__, error)[-1].strip(),
            }
        self.store.save_task_run(payload)
        return payload


def record_successful_skip(command: str, argv: list[str], reason: str, store: JsonStore | None = None) -> dict[str, Any]:
    recorder = TaskRunRecorder(command=command, argv=argv, store=store or JsonStore())
    recorder.start()
    payload = recorder.finish(status="skipped")
    payload["skip_reason"] = reason
    recorder.store.save_task_run(payload)
    return payload
