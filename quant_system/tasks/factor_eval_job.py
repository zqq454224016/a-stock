"""因子有效性评估任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.evaluation.factor_effectiveness import build_factor_effectiveness_payload
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def _load_payload_map(store: JsonStore, folder: str) -> dict[str, dict[str, Any]]:
    base = store.config.json_data_dir / folder
    out: dict[str, dict[str, Any]] = {}
    if not base.exists():
        return out
    for path in sorted(base.glob("*.json")):
        if path.stem == "index":
            continue
        payload = store.read(path)
        if isinstance(payload, dict):
            out[path.stem] = payload
    return out


def run_factor_eval_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    payload = build_factor_effectiveness_payload(
        stocks=_load_payload_map(store, "stocks"),
        current_factors=_load_payload_map(store, "factors"),
    )
    store.save_factor_eval(payload)
    logger.info(
        "因子有效性评估完成: stocks=%s samples=%s",
        payload.get("stock_count"), payload.get("sample_count"),
    )
    return payload
