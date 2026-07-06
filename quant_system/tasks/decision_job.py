"""单股指导性决策任务。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.agent.orchestrator import build_agent_report
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.decision.engine import build_stock_decision
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.impact_job import run_impact_job
from quant_system.tasks.predict_job import run_predict_job
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _read_json_if_exists(store: JsonStore, rel: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / rel
    if path.exists():
        return store.read(path)
    return None


def _load_account(store: JsonStore) -> dict[str, Any] | None:
    path = store.trading_dir() / "account.json"
    if path.exists():
        return store.read(path)
    return None


def run_decision_job(
    codes: list[str] | None = None,
    *,
    strategy: str = "ma_cross",
    auto_predict: bool = True,
    auto_agent: bool = True,
    auto_impact: bool = True,
) -> list[dict[str, Any]]:
    """生成单股操作建议。"""
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())
    account = _load_account(store)

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股")
        return []

    decisions: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        try:
            ctx = StockContext(code, store)
            stock = ctx.stock or {}
            prediction = ctx.prediction
            if not prediction and auto_predict:
                run_predict_job(codes=[code], strategy_name=strategy)
                prediction = ctx.prediction

            agent_report = _read_json_if_exists(store, f"agent/{code}.json")
            if not agent_report and auto_agent:
                agent_report = build_agent_report(ctx, strategy=strategy)
                store.save_agent_report(code, agent_report)

            impact = ctx.impact
            if not impact and auto_impact:
                run_impact_job(codes=[code])
                impact = ctx.impact

            decision = build_stock_decision(
                code=code,
                name=stock.get("name") or item.get("name") or code,
                trade_date=stock.get("trade_date") or "",
                stock=stock,
                prediction=prediction,
                factors=ctx.factors,
                backtest=ctx.backtest(strategy),
                quality=ctx.quality,
                agent_report=agent_report,
                impact=impact,
                account=account,
            )
            store.save_decision(code, decision)
            decisions.append(decision)
            index.append({
                "code": code,
                "name": decision.get("name"),
                "trade_date": decision.get("trade_date"),
                "action": decision.get("action"),
                "position_suggestion": decision.get("position_suggestion"),
                "confidence": decision.get("confidence"),
                "requires_human_review": decision.get("requires_human_review"),
            })
            logger.info(
                "决策 %s: action=%s position=%s confidence=%s",
                code, decision.get("action"), decision.get("position_suggestion"), decision.get("confidence"),
            )
        except Exception as e:
            logger.error("决策 %s 失败: %s", code, e)

    if index:
        store.save_decision_index(index, now_str())
    logger.info("decision 完成，共 %s 只", len(decisions))
    return decisions
