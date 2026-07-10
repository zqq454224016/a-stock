from __future__ import annotations

from pathlib import Path

from quant_system.config.db_config import DBConfig
from quant_system.monitoring.task_runs import TaskRunRecorder
from quant_system.storage.json_store import JsonStore


def _store(tmp_path: Path) -> JsonStore:
    store = JsonStore(DBConfig())
    store.config.json_data_dir = tmp_path
    return store


def test_task_run_recorder_writes_success_record_and_index(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recorder = TaskRunRecorder(command="monitor", argv=["monitor"], store=store)

    recorder.start()
    payload = recorder.finish()

    assert payload["status"] == "success"
    assert (tmp_path / "task_runs" / f"{payload['run_id']}.json").exists()
    index = store.read(tmp_path / "task_runs" / "index.json")
    assert index["runs"][0]["run_id"] == payload["run_id"]
    assert index["runs"][0]["command"] == "monitor"
    assert index["runs"][0]["status"] == "success"


def test_task_run_recorder_writes_failure_summary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recorder = TaskRunRecorder(command="selector", argv=["selector"], store=store)
    error = ValueError("阈值异常")

    recorder.start()
    payload = recorder.finish(status="failed", error=error)

    index = store.read(tmp_path / "task_runs" / "index.json")
    assert payload["error"]["type"] == "ValueError"
    assert index["runs"][0]["status"] == "failed"
    assert index["runs"][0]["error"]["message"] == "阈值异常"


def test_task_run_index_keeps_latest_100_records(tmp_path: Path) -> None:
    store = _store(tmp_path)

    for i in range(105):
        store.save_task_run({
            "run_id": f"run_{i:03d}",
            "command": "monitor",
            "argv": ["monitor"],
            "status": "success",
            "started_at": f"2026-07-10 10:{i % 60:02d}:00",
            "ended_at": f"2026-07-10 10:{i % 60:02d}:01",
            "duration_sec": 1,
            "artifacts": [],
        })

    index = store.read(tmp_path / "task_runs" / "index.json")
    assert len(index["runs"]) == 100
    assert index["runs"][0]["run_id"] == "run_104"
    assert index["runs"][-1]["run_id"] == "run_005"
