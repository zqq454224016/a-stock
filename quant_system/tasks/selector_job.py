"""上涨候选池筛选任务。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.selector.builder import build_upside_candidate
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.impact_job import run_impact_job
from quant_system.tasks.predict_job import run_predict_job
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def run_selector_job(
    codes: list[str] | None = None,
    *,
    strategy: str = "ma_cross",
    auto_predict: bool = True,
    auto_impact: bool = True,
) -> list[dict[str, Any]]:
    """生成上涨候选池排名。"""
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())
    stocks = [{"code": normalize_code(c), "name": ""} for c in codes] if codes else load_watchlist(cfg)
    if not stocks:
        logger.error("未配置自选股")
        return []

    rows: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        ctx = StockContext(code, store)
        prediction = ctx.prediction
        if not prediction and auto_predict:
            run_predict_job(codes=[code], strategy_name=strategy)
            prediction = ctx.prediction
        impact = ctx.impact
        if not impact and auto_impact:
            run_impact_job(codes=[code])
            impact = ctx.impact

        candidate = build_upside_candidate(
            code=code,
            name=(ctx.stock or {}).get("name") or item.get("name") or code,
            stock=ctx.stock,
            prediction=prediction,
            factors=ctx.factors,
            backtest=ctx.backtest(strategy),
            quality=ctx.quality,
            impact=impact,
        )
        store.save_selector(code, candidate)
        rows.append(candidate)
        logger.info(
            "上涨候选 %s: score=%s status=%s",
            code, candidate.get("upside_score"), candidate.get("status"),
        )

    rows.sort(key=lambda x: float(x.get("upside_score") or 0), reverse=True)
    store.save_selector_index([
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "trade_date": r.get("trade_date"),
            "upside_score": r.get("upside_score"),
            "status": r.get("status"),
            "rank_bucket": r.get("rank_bucket"),
            "top_reason": (r.get("reasons") or [""])[0],
            "top_risk": (r.get("risks") or [""])[0],
            "reject_reasons": r.get("reject_reasons") or [],
        }
        for r in rows
    ], now_str())
    return rows
