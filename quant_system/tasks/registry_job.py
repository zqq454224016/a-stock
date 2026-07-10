"""数据注册表任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.registry import build_data_registry
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def run_registry_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    payload = build_data_registry(store)
    for item in payload.get("items") or []:
        store.save_data_registry_item(str(item.get("module")), item)
    store.save_data_registry_index(payload)
    summary = payload.get("summary") or {}
    logger.info(
        "数据注册表完成: artifacts=%s existing=%s missing=%s degraded=%s lineage=%s",
        summary.get("artifact_count"),
        summary.get("existing_count"),
        summary.get("missing_count"),
        summary.get("degraded_count"),
        summary.get("with_task_lineage_count"),
    )
    return payload
