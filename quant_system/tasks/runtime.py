"""Shared task runtime helpers for watchlist-based jobs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.utils.concurrent_fetch import run_parallel_map
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)
T = TypeVar("T")


def resolve_stock_items(
    cfg: CrawlerConfig,
    *,
    codes: Iterable[str] | None = None,
    reason: str,
    research_only: bool = True,
) -> list[dict[str, Any]]:
    if codes:
        return [{"code": normalize_code(c), "name": ""} for c in codes]
    items = load_watchlist(cfg)
    if research_only:
        return filter_research_stocks(items, cfg, reason=reason)
    return items


def run_for_watchlist(
    *,
    cfg: CrawlerConfig,
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], T | None],
    label: str,
    empty_message: str = "未配置自选股",
    on_success: Callable[[list[T], str], None] | None = None,
    save_when_empty: bool = False,
) -> list[T]:
    if not items:
        logger.error(empty_message)
        return []
    results = run_parallel_map(
        items,
        worker,
        max_workers=cfg.fetch_workers,
        label=label,
    )
    index = [r for r in results if r is not None]
    if on_success and (index or save_when_empty):
        on_success(index, now_str())
    return index
