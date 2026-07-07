"""市场范围与参考标的过滤。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def is_star_board_code(code: str) -> bool:
    """科创板股票代码。"""
    c = normalize_code(code)
    return c.startswith(("688", "689"))


def is_reference_only_stock(code: str, cfg: CrawlerConfig | None = None) -> bool:
    """默认只作为参考，不进入重型研究链路。"""
    cfg = cfg or CrawlerConfig()
    return cfg.star_board_reference_only and is_star_board_code(code)


def filter_research_stocks(stocks: list[dict], cfg: CrawlerConfig | None = None, *, reason: str = "") -> list[dict]:
    """过滤默认研究范围，跳过只作为参考的标的。"""
    cfg = cfg or CrawlerConfig()
    kept: list[dict] = []
    skipped: list[str] = []
    for item in stocks:
        code = normalize_code(item.get("code", ""))
        if is_reference_only_stock(code, cfg):
            skipped.append(code)
            continue
        kept.append(item)
    if skipped:
        suffix = f"（{reason}）" if reason else ""
        logger.info("科创板参考标的跳过重型链路%s: %s", suffix, ", ".join(skipped))
    return kept
