"""AI stock diagnosis task."""

from __future__ import annotations

from quant_system.ai import diagnose_stock
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.runtime import resolve_stock_items
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def run_diagnosis_job(codes: list[str] | None = None, *, focus: str = "") -> list[str]:
    items = resolve_stock_items(CrawlerConfig(), codes=codes, reason="AI 诊股", research_only=True)
    outputs: list[str] = []
    for item in items:
        path = diagnose_stock(item["code"], focus=focus)
        outputs.append(str(path))
        logger.info("AI 诊股已生成: %s", path)
    return outputs
