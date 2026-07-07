"""数据质量巡检任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.kline_loader import load_kline_df
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.pipeline.quality_inspector import build_inspect_report, inspect_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.backfill_job import run_backfill
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

logger = get_logger(__name__)


def _inspect_codes(
    stocks: list[dict],
    api: AkShareAPI,
    cfg: CrawlerConfig,
    store: JsonStore,
    lookback_days: int,
) -> list[dict[str, Any]]:
    cal = get_calendar()
    results: list[dict[str, Any]] = []
    for item in stocks:
        code = normalize_code(item["code"])
        try:
            df, _meta = load_kline_df(code, api, cfg, store)
            report = inspect_kline_df(code, df, calendar=cal, lookback_days=lookback_days)
            results.append(report)
            logger.info(
                "巡检 %s: %s score=%s 缺失=%s",
                code, report["status"], report.get("quality_score"),
                len(report.get("missing_dates", [])),
            )
        except Exception as e:
            logger.error("巡检 %s 失败: %s", code, e)
            results.append({
                "code": code,
                "status": "error",
                "quality_score": 0,
                "factor_eligible": False,
                "issues": [str(e)],
                "missing_dates": [],
                "checked_at": now_str(),
            })
    return results


def run_data_inspect(
    codes: list[str] | None = None,
    auto_fix: bool = False,
    lookback_days: int = 60,
) -> dict[str, Any]:
    """巡检自选股 K 线质量；auto_fix 时 backfill 并刷新 stocks。"""
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())

    try:
        get_calendar().fetch_dates()
    except Exception as e:
        logger.error("交易日历不可用，跳过巡检: %s", e)
        return {"error": str(e)}

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = filter_research_stocks(load_watchlist(cfg), cfg, reason="质量巡检")

    if not stocks:
        logger.error("未配置自选股")
        return {"error": "empty watchlist"}

    results = _inspect_codes(stocks, api, cfg, store, lookback_days)
    fix_codes = [r["code"] for r in results if r.get("status") != "ok"]

    if auto_fix and fix_codes:
        logger.info("自动修复: %s", ", ".join(fix_codes))
        backfill_days = max(cfg.stock_hist_days, cfg.mvp_hist_days)
        run_backfill(fix_codes, days=backfill_days, refresh_stocks=True)
        results = _inspect_codes(stocks, api, cfg, store, lookback_days)

    payload = build_inspect_report(results, now_str())
    store.save_quality_report(payload)
    logger.info(
        "data_inspect 完成: ok=%s warning=%s error=%s blocked=%s",
        payload["summary"].get("ok", 0),
        payload["summary"].get("warning", 0),
        payload["summary"].get("error", 0),
        payload["summary"].get("factor_blocked", 0),
    )
    return payload
