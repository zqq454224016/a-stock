"""监控告警与数据血缘任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.monitoring import build_monitoring_snapshot
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.registry_job import run_registry_job
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def run_monitoring_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    run_registry_job()
    payload = build_monitoring_snapshot(store)
    store.save_monitoring_snapshot(payload)
    summary = payload.get("summary") or {}
    logger.info(
        "监控快照完成: modules=%s critical=%s warning=%s",
        summary.get("module_count"),
        summary.get("critical_alerts"),
        summary.get("warning_alerts"),
    )
    return payload
