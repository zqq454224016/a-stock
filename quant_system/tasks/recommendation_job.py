"""多周期股票推荐任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.recommendation.builder import build_recommendation_payload
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


def run_recommendation_job(limit: int = 5) -> dict[str, Any]:
    store = JsonStore(DBConfig())
    payload = build_recommendation_payload(
        market=_read(store, "latest.json"),
        stocks=_load_map(store, "stocks"),
        selectors=_load_map(store, "selector"),
        predictions=_load_map(store, "predictions"),
        factors=_load_map(store, "factors"),
        impacts=_load_map(store, "impact"),
        enhances=_load_map(store, "enhance"),
        replays=_load_map(store, "replay"),
        limit=limit,
    )
    store.save_recommendations(payload)
    counts = {key: len(value["recommendations"]) for key, value in payload["periods"].items()}
    logger.info("多周期推荐完成: %s", counts)
    return payload
