"""候选、预测和决策的后验复盘任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.evaluation.review import build_review_payload
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _read_optional(store: JsonStore, rel: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / rel
    if not path.exists():
        return None
    try:
        return store.read(path)
    except Exception:
        return None


def _resolve_items(codes: list[str] | None, cfg: CrawlerConfig) -> list[dict[str, str]]:
    if codes:
        return [{"code": normalize_code(c), "name": ""} for c in codes]
    return filter_research_stocks(load_watchlist(cfg), cfg, reason="后验复盘")


def run_review_job(codes: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())
    items = _resolve_items(codes, cfg)
    if not items:
        logger.error("未配置自选股")
        return []

    payloads: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for item in items:
        code = normalize_code(item["code"])
        stock = _read_optional(store, f"stocks/{code}.json")
        name = item.get("name") or (stock or {}).get("name") or code
        payload = build_review_payload(
            code=code,
            name=name,
            stock=stock,
            prediction=_read_optional(store, f"predictions/{code}.json"),
            selector=_read_optional(store, f"selector/{code}.json"),
            decision=_read_optional(store, f"decisions/{code}.json"),
        )
        store.save_review(code, payload)
        summary = payload.get("summary") or {}
        index.append({
            "code": code,
            "name": payload.get("name"),
            "status": payload.get("status"),
            "trade_date": payload.get("trade_date"),
            "evaluated_count": summary.get("evaluated_count"),
            "pending_count": summary.get("pending_count"),
            "hit_rate": summary.get("hit_rate"),
            "avg_return_pct": summary.get("avg_return_pct"),
            "worst_adverse_pct": summary.get("worst_adverse_pct"),
        })
        payloads.append(payload)
        logger.info(
            "后验复盘 %s: evaluated=%s pending=%s hit_rate=%s",
            code, summary.get("evaluated_count"), summary.get("pending_count"), summary.get("hit_rate"),
        )

    store.save_review_index(index, now_str())
    return payloads
