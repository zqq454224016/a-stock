from __future__ import annotations

import json
from pathlib import Path

from quant_system.config.db_config import DBConfig
from quant_system.registry import build_data_registry
from quant_system.storage.json_store import JsonStore


def _store(tmp_path: Path) -> JsonStore:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    return store


def _write(base: Path, rel: str, payload: dict) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_data_registry_summarizes_artifact_fields_and_quality(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write(tmp_path, "latest.json", {
        "updated_at": "2026-07-10 10:00:00",
        "trade_date": "2026-07-10",
        "indices": [],
        "degraded": True,
        "limitations": ["spot_watchlist_only"],
    })

    payload = build_data_registry(store)
    market = next(item for item in payload["items"] if item["module"] == "market")

    assert payload["summary"]["artifact_count"] > 0
    assert market["exists"] is True
    assert market["record_count"] == 1
    assert "indices" in market["field_summary"]["top_level_fields"]
    assert market["data_quality"]["degraded"] is True
    assert "spot_watchlist_only" in market["data_quality"]["limitations"]
    assert market["source"]["expected_command"] == "market"


def test_data_registry_links_latest_task_run_to_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _write(tmp_path, "selector/index.json", {
        "updated_at": "2026-07-10 10:00:00",
        "items": [{"code": "600001"}],
    })
    _write(tmp_path, "task_runs/index.json", {
        "updated_at": "2026-07-10 10:01:00",
        "runs": [{
            "run_id": "run_001",
            "command": "selector",
            "status": "success",
            "ended_at": "2026-07-10 10:01:00",
            "duration_sec": 1.2,
            "artifacts": [{"path": "selector/index.json", "exists": True}],
        }],
    })

    payload = build_data_registry(store)
    selector = next(item for item in payload["items"] if item["module"] == "selector")

    assert selector["generated_by"]["run_id"] == "run_001"
    assert selector["generated_by"]["command"] == "selector"
    assert selector["record_count"] == 1
    assert any(row["module"] == "selector" and row["generated_by"] == "selector" for row in payload["lineage"])
