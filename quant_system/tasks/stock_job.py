"""自选股分析采集任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.adjuster import apply_adjustment
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, normalize_kline_df, to_symbol
from quant_system.pipeline.stock_analyzer import build_stock_analysis
from quant_system.pipeline.validator import validate_kline_df
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def run_daily_stock(codes: list[str] | None = None) -> list[dict]:
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股，请编辑 assets/data/watchlist.json")
        return []

    codes_list = [normalize_code(item["code"]) for item in stocks]
    spot_map = api.fetch_spot_map(codes=codes_list)
    index: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        name = item.get("name", "")
        symbol = to_symbol(code)
        try:
            logger.info("采集个股 %s (%s)", code, name or symbol)
            raw_df = api.fetch_daily_hist(symbol, adjust="qfq")
            df = normalize_kline_df(raw_df, code, days=cfg.stock_hist_days)
            df = clean_kline_df(df)
            df = apply_adjustment(df, adj_type="qfq")
            validate_kline_df(df)

            spot = spot_map.get(code)
            data = build_stock_analysis(code, name, df, spot)
            store.save_stock_analysis(code, data)

            index.append({
                "code": code,
                "name": data["name"],
                "trade_date": data["trade_date"],
                "close": data["quote"]["close"],
                "change_pct": data["quote"]["change_pct"],
                "trend": data["analysis"]["trend"],
                "report": f"reports/stock/{code}.html",
            })
        except Exception as e:
            logger.error("个股 %s 失败: %s", code, e)

    store.save_stock_index(index, now_str())
    logger.info("daily_stock 完成，共 %s 只", len(index))
    return index
