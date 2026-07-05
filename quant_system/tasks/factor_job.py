"""技术因子计算任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.factors.signal import compute_primary_signal
from quant_system.factors.technical import compute_technical_factors
from quant_system.pipeline.kline_loader import load_kline_df, load_stock_context
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.pipeline.quality_gate import factor_block_reason, load_quality_map
from quant_system.pipeline.quality_inspector import inspect_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.factor_utils import save_composite_factors
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

logger = get_logger(__name__)


def run_factor_compute(
    codes: list[str] | None = None,
    *,
    ignore_quality: bool = False,
) -> list[dict[str, Any]]:
    """计算自选股技术因子；默认遵守质量门禁。"""
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    quality_map = {} if ignore_quality else load_quality_map(store)

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股")
        return []

    cal = get_calendar()
    index: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        try:
            if not ignore_quality and code in quality_map:
                reason = factor_block_reason(quality_map[code])
                if reason:
                    logger.warning("因子跳过 %s: %s", code, reason)
                    continue

            df, meta = load_kline_df(code, api, cfg, store)
            if not ignore_quality and code not in quality_map:
                q = inspect_kline_df(code, df, calendar=cal)
                reason = factor_block_reason(q)
                if reason:
                    logger.warning("因子跳过 %s（现场巡检）: %s", code, reason)
                    continue

            ctx = load_stock_context(code, store)
            result = compute_technical_factors(
                df, code,
                trade_date=ctx.get("trade_date") or meta.get("trade_date"),
                close_override=ctx.get("close_override"),
                data_version=meta.get("data_version"),
            )
            composite = save_composite_factors(code, result["trade_date"], result, store)
            f = composite["factors"]
            signal_payload = compute_primary_signal(f, code, composite["trade_date"])
            store.save_signal(code, signal_payload)
            index.append({
                "code": code,
                "trade_date": composite["trade_date"],
                "factor_version": composite.get("factor_version"),
                "ma20_bias": f.get("ma20_bias"),
                "rsi14": f.get("rsi14"),
                "momentum_20": f.get("momentum_20"),
                "ma_cross": f.get("ma_cross"),
                "multi_factor_score": f.get("multi_factor_score"),
                "sentiment_score": f.get("sentiment_score"),
                "primary_signal": signal_payload.get("signal"),
            })
            logger.info(
                "因子 %s: multi=%s tech=%s sent=%s",
                code, f.get("multi_factor_score"), f.get("technical_score"), f.get("sentiment_score"),
            )
        except Exception as e:
            logger.error("因子计算 %s 失败: %s", code, e)

    if index:
        store.save_factor_index(index, now_str())
    logger.info("factor_compute 完成，共 %s 只", len(index))
    return index
