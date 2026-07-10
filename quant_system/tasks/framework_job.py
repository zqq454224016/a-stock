"""模块化算法框架快照任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.contracts import build_framework_snapshot
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def _read(store: JsonStore, rel: str) -> dict[str, Any]:
    path = store.config.json_data_dir / rel
    return store.read(path) if path.exists() else {}


def _load_map(store: JsonStore, folder: str) -> dict[str, dict[str, Any]]:
    base = store.config.json_data_dir / folder
    if not base.exists():
        return {}
    return {
        path.stem: store.read(path)
        for path in sorted(base.glob("*.json"))
        if path.stem != "index"
    }


def run_framework_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    payload = build_framework_snapshot(
        stocks=_load_map(store, "stocks"),
        predictions=_load_map(store, "predictions"),
        selectors=_load_map(store, "selector"),
        decisions=_load_map(store, "decisions"),
        impacts=_load_map(store, "impact"),
        replays=_load_map(store, "replay"),
        recommendations=_read(store, "recommendations/summary.json"),
    )
    store.save_framework_snapshot(payload)
    coverage = payload.get("coverage") or {}
    logger.info(
        "模块化框架快照完成: universe=%s signals=%s",
        coverage.get("universe_count"),
        coverage.get("signal_count"),
    )
    return payload
