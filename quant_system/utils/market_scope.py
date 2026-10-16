"""市场范围与参考标的过滤。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)
RESEARCH_STOCK_PREFIXES = ("000", "001", "002", "003", "600", "601", "603", "605")


def is_star_board_code(code: str) -> bool:
    """科创板股票代码。"""
    c = normalize_code(code)
    return c.startswith(("688", "689"))


def is_chinext_code(code: str) -> bool:
    """创业板股票代码。"""
    c = normalize_code(code)
    return c.startswith(("300", "301"))


def is_beijing_exchange_code(code: str) -> bool:
    """北交所股票代码，兼容 920 新号段及存量历史号段。"""
    c = normalize_code(code)
    return c.startswith(("4", "8", "920"))


def is_additional_permission_board_code(code: str) -> bool:
    """需要在普通 A 股账户之外另行开通交易权限的板块。"""
    return is_star_board_code(code) or is_chinext_code(code) or is_beijing_exchange_code(code)


def is_research_stock_code(code: str) -> bool:
    """Ordinary Shanghai/Shenzhen main-board A-share code used system-wide."""
    c = normalize_code(code)
    return len(c) == 6 and c.isdigit() and c.startswith(RESEARCH_STOCK_PREFIXES)


def is_reference_only_stock(code: str, cfg: CrawlerConfig | None = None) -> bool:
    """默认只作为参考，不进入重型研究链路。"""
    cfg = cfg or CrawlerConfig()
    return cfg.star_board_reference_only and is_star_board_code(code)


def filter_research_stocks(stocks: list[dict], cfg: CrawlerConfig | None = None, *, reason: str = "") -> list[dict]:
    """过滤默认研究范围，排除当前账户需要额外权限的板块。"""
    cfg = cfg or CrawlerConfig()
    kept: list[dict] = []
    skipped: list[str] = []
    for item in stocks:
        code = normalize_code(item.get("code", ""))
        if not is_research_stock_code(code):
            skipped.append(code)
            continue
        kept.append(item)
    if skipped:
        suffix = f"（{reason}）" if reason else ""
        examples = ", ".join(skipped[:8])
        more = f" 等，共 {len(skipped)} 只" if len(skipped) > 8 else ""
        logger.info("额外权限板块已跳过重型链路%s: %s%s", suffix, examples, more)
    return kept
