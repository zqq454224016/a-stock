"""每日涨跌归因任务。"""

from __future__ import annotations

from typing import Any

from quant_system.attribution import build_daily_attribution_payload
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
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
        payload = store.read(path)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def run_attribution_job(codes: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())
    stocks = (
        [{"code": normalize_code(c), "name": ""} for c in codes]
        if codes else filter_research_stocks(load_watchlist(cfg), cfg, reason="每日归因")
    )
    if not stocks:
        logger.error("未配置自选股")
        return []

    market = _read_optional(store, "latest.json") or _read_optional(store, "indices/benchmarks.json")
    payloads: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        stock = _read_optional(store, f"stocks/{code}.json")
        if not stock:
            logger.warning("每日归因跳过 %s: 缺少 stocks/%s.json", code, code)
            continue
        name = item.get("name") or stock.get("name") or code
        payload = build_daily_attribution_payload(
            code,
            name,
            stock,
            market=market,
            impact=_read_optional(store, f"impact/{code}.json"),
            replay=_read_optional(store, f"replay/{code}.json"),
        )
        store.save_attribution(code, payload)
        summary = payload.get("summary") or {}
        logic = payload.get("logic_review") or {}
        index.append({
            "code": code,
            "name": name,
            "status": payload.get("status"),
            "trade_date": payload.get("trade_date"),
            "previous_trade_date": payload.get("previous_trade_date"),
            "pattern": payload.get("pattern"),
            "yesterday_return_pct": summary.get("yesterday_return_pct"),
            "today_return_pct": summary.get("today_return_pct"),
            "logic_broken": logic.get("logic_broken"),
            "primary_today_causes": summary.get("primary_today_causes") or [],
            "limitations": payload.get("limitations") or [],
        })
        payloads.append(payload)
        logger.info(
            "每日归因 %s: pattern=%s logic_broken=%s",
            code, payload.get("pattern"), logic.get("logic_broken"),
        )
    store.save_attribution_index(index, now_str())
    return payloads
