"""P1-3 数据增强任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.enhance_api import EnhanceAPI
from quant_system.pipeline.enhance_builder import build_enhance_payload, summarize_enhance
from quant_system.pipeline.normalizer import normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.tasks.runtime import resolve_stock_items, run_for_watchlist

logger = get_logger(__name__)


def _load_stock_context(store: JsonStore, code: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    path = store.config.json_data_dir / "stocks" / f"{code}.json"
    if not path.exists():
        return None, None
    data = store.read(path)
    return data, data.get("quality")


def _load_market(store: JsonStore) -> dict[str, Any] | None:
    path = store.config.json_data_dir / "latest.json"
    if not path.exists():
        return None
    return store.read(path)


def _process_one_stock(
    item: dict[str, Any],
    api: EnhanceAPI,
    store: JsonStore,
    market: dict[str, Any] | None,
) -> dict[str, Any] | None:
    code = normalize_code(item["code"])
    name = item.get("name", "")
    try:
        stock_data, quality = _load_stock_context(store, code)
        if stock_data and not name:
            name = stock_data.get("name", "")

        bundle = api.fetch_stock_bundle(code)
        failed: list[str] = list(bundle.get("failed") or [])

        payload = build_enhance_payload(
            code,
            name,
            valuation=bundle.get("valuation") or {},
            dividends=bundle.get("dividends") or [],
            lockups=bundle.get("lockups") or [],
            forecast=bundle.get("forecast"),
            northbound=bundle.get("northbound") or {},
            margin=bundle.get("margin"),
            market=market,
            stock_analysis=stock_data,
            quality=quality,
            sources_failed=failed,
        )
        store.save_enhance(code, payload)
        summary = summarize_enhance(payload)
        logger.info(
            "增强 %s: PE=%s PB=%s 北向持股=%s%% 分红=%s条",
            code,
            summary.get("pe_ttm"),
            summary.get("pb"),
            summary.get("north_hold_pct"),
            summary.get("dividend_count"),
        )
        return summary
    except Exception as e:
        logger.error("增强 %s 失败: %s", code, e)
        return None


def run_enhance_job(codes: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    api = EnhanceAPI(cfg)
    store = JsonStore(DBConfig())

    stocks = resolve_stock_items(cfg, codes=codes, reason="数据增强")

    market = _load_market(store)
    worker = lambda item: _process_one_stock(item, api, store, market)

    def _save_index(rows: list[dict[str, Any]], ts: str) -> None:
        store.save_enhance_index(rows, ts)
        store.save_index_benchmarks(market or {}, ts)

    index = run_for_watchlist(
        cfg=cfg,
        items=stocks,
        worker=worker,
        label="数据增强",
        on_success=_save_index,
    )

    logger.info("数据增强完成，共 %s 只", len(index))
    return index
