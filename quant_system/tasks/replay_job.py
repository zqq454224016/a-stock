"""历史视角滚动推演任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.kline_loader import load_kline_df
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.replay.walk_forward import build_replay_payload
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _resolve_name(store: JsonStore, item: dict[str, Any], code: str) -> str:
    if item.get("name"):
        return item["name"]
    path = store.config.json_data_dir / "stocks" / f"{code}.json"
    if path.exists():
        return store.read(path).get("name") or code
    return code


def _read_optional(store: JsonStore, rel: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / rel
    if not path.exists():
        return None
    try:
        return store.read(path)
    except Exception:
        return None


def _build_context(store: JsonStore, code: str) -> dict[str, Any]:
    market = _read_optional(store, "latest.json") or _read_optional(store, "indices/benchmarks.json")
    return {
        "market": market,
        "enhance": _read_optional(store, f"enhance/{code}.json"),
        "impact": _read_optional(store, f"impact/{code}.json"),
    }


def run_replay_job(codes: list[str] | None = None, *, days: int = 10) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    stocks = (
        [{"code": normalize_code(c), "name": ""} for c in codes]
        if codes else filter_research_stocks(load_watchlist(cfg), cfg, reason="历史推演")
    )
    if not stocks:
        logger.error("未配置自选股")
        return []

    payloads: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        try:
            df, _meta = load_kline_df(code, api, cfg, store, prefer_api=False, days=max(260, days + 60))
            payload = build_replay_payload(
                code,
                _resolve_name(store, item, code),
                df,
                days=days,
                context=_build_context(store, code),
            )
            store.save_replay(code, payload)
            summary = payload.get("summary") or {}
            index.append({
                "code": code,
                "name": payload.get("name"),
                "status": payload.get("status"),
                "window_days": payload.get("window_days"),
                "start_knowledge_cutoff": payload.get("start_knowledge_cutoff"),
                "end_target_date": payload.get("end_target_date"),
                "step_count": summary.get("step_count"),
                "hit_rate": summary.get("hit_rate"),
                "total_return_pct": summary.get("total_return_pct"),
                "up_prediction_count": summary.get("up_prediction_count"),
                "down_prediction_count": summary.get("down_prediction_count"),
            })
            payloads.append(payload)
            logger.info(
                "历史推演 %s: steps=%s hit_rate=%s return=%s%%",
                code, summary.get("step_count"), summary.get("hit_rate"), summary.get("total_return_pct"),
            )
        except Exception as e:
            logger.error("历史推演 %s 失败: %s", code, e)

    store.save_replay_index(index, now_str())
    return payloads
