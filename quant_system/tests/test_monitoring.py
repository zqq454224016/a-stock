from __future__ import annotations

import json
from pathlib import Path

from quant_system.config.db_config import DBConfig
from quant_system.monitoring import build_monitoring_snapshot
from quant_system.storage.json_store import JsonStore


def _write(base: Path, rel: str, payload: dict) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_monitoring_snapshot_reports_missing_modules(tmp_path: Path) -> None:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    _write(tmp_path, "latest.json", {"updated_at": "2026-07-10 10:00:00", "indices": []})

    payload = build_monitoring_snapshot(store)

    assert payload["summary"]["module_count"] > 0
    assert payload["summary"]["missing_count"] > 0
    assert any(x["level"] == "critical" for x in payload["alerts"])
    assert any(x["module"] == "market" for x in payload["lineage"])


def test_monitoring_snapshot_reads_quality_and_recommendation_alerts(tmp_path: Path) -> None:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    _write(tmp_path, "quality/latest.json", {
        "updated_at": "2026-07-10 10:00:00",
        "summary": {"ok": 1, "warning": 1, "error": 0, "factor_blocked": 1},
        "stocks": [],
    })
    _write(tmp_path, "recommendations/summary.json", {
        "updated_at": "2026-07-10 10:00:00",
        "periods": {"short": {"label": "短线", "evaluated": [], "shortage_count": 5}},
    })

    payload = build_monitoring_snapshot(store)
    messages = [x["message"] for x in payload["alerts"]]

    assert any("质量警告" in x for x in messages)
    assert any("推荐缺额" in x for x in messages)


def test_monitoring_snapshot_reads_recent_task_failures(tmp_path: Path) -> None:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    _write(tmp_path, "task_runs/index.json", {
        "updated_at": "2026-07-10 10:00:00",
        "runs": [{
            "run_id": "run_001",
            "command": "selector",
            "argv": ["selector"],
            "status": "failed",
            "started_at": "2026-07-10 10:00:00",
            "ended_at": "2026-07-10 10:00:01",
            "duration_sec": 1,
            "error": {"type": "ValueError", "message": "阈值异常"},
            "artifacts": [],
            "path": "task_runs/run_001.json",
        }],
    })

    payload = build_monitoring_snapshot(store)

    assert payload["summary"]["failed_task_runs"] == 1
    assert payload["summary"]["last_task_command"] == "selector"
    assert payload["recent_task_runs"][0]["status"] == "failed"
    assert any(x["module"] == "task_runs" and "失败" in x["message"] for x in payload["alerts"])


def test_monitoring_snapshot_reads_data_registry_summary(tmp_path: Path) -> None:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    _write(tmp_path, "data_registry/index.json", {
        "updated_at": "2026-07-10 10:00:00",
        "summary": {
            "artifact_count": 3,
            "existing_count": 2,
            "missing_count": 1,
            "degraded_count": 1,
            "with_task_lineage_count": 2,
        },
        "lineage": [{"module": "market", "label": "大盘行情", "inputs": [], "output": "latest.json", "generated_by": "market", "input_status": {}}],
        "items": [],
    })

    payload = build_monitoring_snapshot(store)

    assert payload["summary"]["registry_artifact_count"] == 3
    assert payload["summary"]["registry_with_task_lineage_count"] == 2
    assert payload["data_registry"]["summary"]["degraded_count"] == 1
    assert payload["data_registry"]["lineage"][0]["module"] == "market"
