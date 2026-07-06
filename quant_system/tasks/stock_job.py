"""自选股分析采集任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.factors.signal import compute_primary_signal
from quant_system.factors.technical import compute_technical_factors
from quant_system.pipeline.adjuster import apply_adjustment
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.cross_source import run_cross_source_check
from quant_system.pipeline.kline_loader import make_data_version
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, normalize_kline_df, to_symbol
from quant_system.pipeline.kline_merge import merge_spot_into_daily_kline
from quant_system.pipeline.quality_gate import factor_block_reason
from quant_system.pipeline.quality_inspector import inspect_kline_df
from quant_system.pipeline.stock_analyzer import build_stock_analysis
from quant_system.pipeline.validator import validate_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.factor_utils import save_composite_factors
from quant_system.utils.concurrent_fetch import run_parallel_map
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

logger = get_logger(__name__)


def _process_daily_stock(
    item: dict[str, Any],
    api: AkShareAPI,
    store: JsonStore,
    cfg: CrawlerConfig,
    cal: Any,
    spot_map: dict[str, dict],
) -> dict[str, Any] | None:
    code = normalize_code(item["code"])
    name = item.get("name", "")
    symbol = to_symbol(code)
    try:
        logger.info("采集个股 %s (%s)", code, name or symbol)
        raw_df, daily_source = api.fetch_daily_hist(symbol, adjust="qfq")
        df = normalize_kline_df(raw_df, code, days=cfg.stock_hist_days)
        df = clean_kline_df(df)
        df = apply_adjustment(df, adj_type="qfq")

        spot = spot_map.get(code)
        df, merge_meta = merge_spot_into_daily_kline(df, spot, calendar=cal)
        validate_kline_df(df)

        cross_meta = run_cross_source_check(api, cfg, symbol, code, df, daily_source)
        quality = inspect_kline_df(code, df, calendar=cal, cross_source=cross_meta)
        data = build_stock_analysis(code, name, df, spot)
        data["daily_kline_source"] = daily_source
        data["kline_source"] = f"{daily_source}+spot" if merge_meta.get("kline_merged") else daily_source
        data.update(merge_meta)
        data["quality"] = {
            k: quality[k] for k in (
                "status", "quality_score", "missing_rate", "duplicate_count",
                "cross_source_diff", "factor_eligible", "issues", "checked_at",
            ) if k in quality
        }
        data["data_version"] = make_data_version(code, df)
        data["source"] = api.source_name

        block = factor_block_reason(quality)
        if block:
            logger.warning("因子跳过 %s: %s", code, block)
            data["factors"] = None
        else:
            close_override = float(spot["close"]) if spot else None
            factor_payload = compute_technical_factors(
                df, code,
                trade_date=data["trade_date"],
                close_override=close_override,
                data_version=data["data_version"],
            )
            composite = save_composite_factors(code, data["trade_date"], factor_payload, store)
            data["factors"] = composite["factors"]
            signal_payload = compute_primary_signal(
                composite["factors"], code, data["trade_date"],
            )
            data["primary_signal"] = signal_payload
            store.save_signal(code, signal_payload)

        store.save_stock_analysis(code, data)
        return {
            "code": code,
            "name": data["name"],
            "trade_date": data["trade_date"],
            "close": data["quote"]["close"],
            "change_pct": data["quote"]["change_pct"],
            "trend": data["analysis"]["trend"],
            "quality_score": quality.get("quality_score"),
            "primary_signal": (data.get("primary_signal") or {}).get("signal"),
            "report": f"reports/stock/{code}.html",
        }
    except Exception as e:
        logger.error("个股 %s 失败: %s", code, e)
        return None


def run_daily_stock(codes: list[str] | None = None) -> list[dict]:
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    cal = get_calendar()

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股，请编辑 assets/data/watchlist.json")
        return []

    codes_list = [normalize_code(item["code"]) for item in stocks]
    spot_map = api.fetch_spot_map(codes=codes_list)

    worker = lambda item: _process_daily_stock(item, api, store, cfg, cal, spot_map)
    results = run_parallel_map(
        stocks,
        worker,
        max_workers=cfg.fetch_workers,
        label="个股采集",
    )
    index = [r for r in results if r is not None]

    store.save_stock_index(index, now_str())
    logger.info("个股采集完成，共 %s 只", len(index))
    return index
