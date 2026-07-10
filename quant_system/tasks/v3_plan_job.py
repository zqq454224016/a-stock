"""v3 路线图生成任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.planning import build_v3_roadmap
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def run_v3_plan_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    payload = build_v3_roadmap()
    store.save_v3_roadmap(payload)
    logger.info("v3 路线图完成: phases=%s next=%s", len(payload["phases"]), payload["current_next"]["id"])
    return payload
