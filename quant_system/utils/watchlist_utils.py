"""自选股 watchlist 工具。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def get_watchlist_codes(cfg: CrawlerConfig | None = None) -> list[str]:
    """返回 watchlist 中全部 6 位代码（唯一来源）。"""
    stocks = load_watchlist(cfg or CrawlerConfig())
    return [normalize_code(s["code"]) for s in stocks]


def get_watchlist_stocks(cfg: CrawlerConfig | None = None) -> list[dict]:
    return load_watchlist(cfg or CrawlerConfig())


def missing_stock_data(codes: list[str] | None = None) -> list[str]:
    """watchlist 中尚未生成 stocks/{code}.json 的代码。"""
    codes = codes or get_watchlist_codes()
    store = JsonStore(DBConfig())
    missing: list[str] = []
    for code in codes:
        path = store.config.json_data_dir / "stocks" / f"{normalize_code(code)}.json"
        if not path.exists():
            missing.append(normalize_code(code))
    return missing


def insufficient_history_codes(
    codes: list[str] | None = None,
    min_days: int | None = None,
) -> list[str]:
    """K 线根数不足 MVP 回测窗口的代码（检查 backfill 归档或 stocks kline）。"""
    cfg = CrawlerConfig()
    min_days = min_days or cfg.mvp_hist_days
    threshold = int(min_days * 0.85)
    target = [normalize_code(c) for c in codes] if codes else get_watchlist_codes()
    store = JsonStore(DBConfig())
    insufficient: list[str] = []

    for code in target:
        rows = 0
        backfill_path = store.config.json_data_dir / "backfill" / f"{code}.json"
        if backfill_path.exists():
            data = store.read(backfill_path)
            rows = len(data.get("klines", []))
        else:
            stock_path = store.config.json_data_dir / "stocks" / f"{code}.json"
            if stock_path.exists():
                data = store.read(stock_path)
                rows = len(data.get("kline", []))
        if rows < threshold:
            insufficient.append(code)
    return insufficient


def ensure_watchlist_history(
    codes: list[str] | None = None,
    min_days: int | None = None,
) -> list[str]:
    """补录不足 MVP 历史窗口的自选股，返回本次 backfill 的代码。"""
    cfg = CrawlerConfig()
    min_days = min_days or cfg.mvp_hist_days
    need = insufficient_history_codes(codes, min_days)
    if not need:
        return []

    from quant_system.tasks.backfill_job import run_backfill

    logger.info("MVP 历史补录 %s 只（目标 %s 日）: %s", len(need), min_days, ", ".join(need))
    run_backfill(need, days=min_days, refresh_stocks=True)
    return need


def ensure_watchlist_stocks(codes: list[str] | None = None) -> list[str]:
    """
    确保 watchlist 条目均有 stocks JSON；缺失则自动采集。
    返回本次补采集的代码列表。
    """
    target = [normalize_code(c) for c in codes] if codes else get_watchlist_codes()
    if not target:
        return []

    missing = missing_stock_data(target)
    if not missing:
        return []

    from quant_system.tasks.stock_job import run_daily_stock

    logger.info("watchlist 缺失数据 %s 只，自动采集: %s", len(missing), ", ".join(missing))
    run_daily_stock(codes=missing)
    return missing


def resolve_codes(codes: list[str] | None) -> list[str] | None:
    """
    CLI 参数解析：None 或空列表 → 使用完整 watchlist；
    有传参 → 仅执行指定代码。
    """
    if codes:
        return [normalize_code(c) for c in codes]
    wl = get_watchlist_codes()
    return wl if wl else None
