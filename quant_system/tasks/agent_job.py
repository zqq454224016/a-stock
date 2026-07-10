"""Agent 分析任务（P4-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.agent.orchestrator import build_agent_report
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def run_agent_job(
    codes: list[str] | None = None,
    *,
    strategy: str = "ma_cross",
    provider: str = "rule",
) -> list[dict[str, Any]]:
    cfg = CrawlerConfig()
    store = JsonStore(DBConfig())

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = filter_research_stocks(load_watchlist(cfg), cfg, reason="Agent 分析")

    if not stocks:
        logger.error("未配置自选股")
        return []

    index: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        try:
            ctx = StockContext(code, store)
            report = build_agent_report(ctx, strategy=strategy, provider=provider)
            audit_record = report.pop("_audit_record", None)
            store.save_agent_report(code, report)
            if audit_record:
                store.save_agent_audit(code, audit_record)
            index.append({
                "code": code,
                "name": report.get("name"),
                "trade_date": report.get("trade_date"),
                "summary": report.get("summary"),
                "confidence": report.get("confidence"),
                "provider": (report.get("provider") or {}).get("active"),
                "policy_passed": (report.get("policy") or {}).get("passed"),
                "selection_verdict": (report.get("stock_selection") or {}).get("verdict"),
                "strategy_verdict": (report.get("strategy_diagnosis") or {}).get("verdict"),
                "prediction_alignment": (report.get("prediction_review") or {}).get("alignment"),
            })
            logger.info(
                "Agent %s: %s [%s] 选股=%s 策略=%s",
                code, report.get("summary"), report.get("confidence"),
                (report.get("stock_selection") or {}).get("verdict"),
                (report.get("strategy_diagnosis") or {}).get("verdict"),
            )
        except Exception as e:
            logger.error("Agent %s 失败: %s", code, e)

    if index:
        store.save_agent_index(index, now_str())
    logger.info("agent 完成，共 %s 只", len(index))
    return index
