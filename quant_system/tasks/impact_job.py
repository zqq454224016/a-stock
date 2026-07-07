"""实际影响数据提取任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.impact.builder import build_impact_payload
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _load_enhance(store: JsonStore, code: str) -> dict[str, Any] | None:
    path = store.enhance_dir() / f"{code}.json"
    if path.exists():
        return store.read(path)
    return None


def run_impact_job(codes: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())
    stocks = (
        [{"code": normalize_code(c), "name": ""} for c in codes]
        if codes else filter_research_stocks(load_watchlist(cfg), cfg, reason="实际影响")
    )
    if not stocks:
        logger.error("未配置自选股")
        return []

    payloads: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        enhance = _load_enhance(store, code)
        name = (enhance or {}).get("name") or item.get("name") or code
        payload = build_impact_payload(code, name, enhance)
        store.save_impact(code, payload)
        payloads.append(payload)
        index.append({
            "code": code,
            "name": name,
            "impact_score": payload.get("impact_score"),
            "impact_direction": payload.get("impact_direction"),
            "event_count": len(payload.get("events") or []),
            "limitations": payload.get("limitations") or [],
        })
        logger.info(
            "影响数据 %s: score=%s direction=%s events=%s",
            code, payload.get("impact_score"), payload.get("impact_direction"), len(payload.get("events") or []),
        )
    store.save_impact_index(index, now_str())
    return payloads
