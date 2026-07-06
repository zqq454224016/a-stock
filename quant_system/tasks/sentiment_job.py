"""舆情采集任务（P1-2）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.sentiment_api import SentimentAPI
from quant_system.factors.sentiment import compute_sentiment_factors
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.concurrent_fetch import run_parallel_map
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _process_sentiment(
    item: dict[str, Any],
    api: SentimentAPI,
    store: JsonStore,
) -> dict[str, Any] | None:
    code = normalize_code(item["code"])
    try:
        raw = api.fetch_stock_sentiment(code)
        factors = compute_sentiment_factors(raw)
        payload = {**raw, "factors": factors}
        store.save_sentiment(code, payload)
        logger.info(
            "舆情 %s: %s 热度=%s 多空比=%s",
            code, factors.get("label"), factors.get("heat_index"), factors.get("long_short_ratio"),
        )
        return {
            "code": code,
            "trade_date": factors.get("trade_date"),
            "label": factors.get("label"),
            "heat_index": factors.get("heat_index"),
            "long_short_ratio": factors.get("long_short_ratio"),
            "sentiment_accel": factors.get("sentiment_accel"),
        }
    except Exception as e:
        logger.error("舆情 %s 失败: %s", code, e)
        return None


def run_sentiment_job(codes: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    api = SentimentAPI(cfg)
    store = JsonStore(DBConfig())

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股")
        return []

    worker = lambda item: _process_sentiment(item, api, store)
    results = run_parallel_map(
        stocks,
        worker,
        max_workers=cfg.fetch_workers,
        label="舆情采集",
    )
    index = [r for r in results if r is not None]

    if index:
        store.save_sentiment_index(index, now_str())
    logger.info("舆情采集完成，共 %s 只", len(index))
    return index
