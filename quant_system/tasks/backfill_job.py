"""历史数据补录任务。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.adjuster import apply_adjustment
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.normalizer import normalize_code, normalize_kline_df, to_symbol
from quant_system.storage.json_store import JsonStore
from quant_system.storage.mysql_client import MySQLClient
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def run_backfill(codes: list[str], days: int = 250, refresh_stocks: bool = True) -> None:
    """
    补录指定股票历史 K 线。
    - 归档写入 assets/data/backfill/{code}.json
    - refresh_stocks=True 时同步刷新 stocks/{code}.json（供巡检/因子使用）
    """
    cfg = CrawlerConfig()
    cfg.stock_hist_days = days
    api = AkShareAPI(cfg)
    store = JsonStore(DBConfig())
    mysql = MySQLClient(DBConfig())
    mysql.connect()

    ok_codes: list[str] = []

    for code in codes:
        code = normalize_code(code)
        symbol = to_symbol(code)
        try:
            raw_df, daily_source = api.fetch_daily_hist(symbol, adjust="qfq")
            df = normalize_kline_df(raw_df, code, days=days)
            df = clean_kline_df(df)
            df = apply_adjustment(df, adj_type="qfq")

            klines = [{
                "date": r["date"].strftime("%Y-%m-%d"),
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r.get("volume", 0)),
                "amount": float(r.get("amount", 0) or 0),
                "adj_factor": 1.0,
                "adj_type": "qfq",
            } for _, r in df.iterrows()]

            out = DBConfig().json_data_dir / "backfill" / f"{code}.json"
            store.write(out, {
                "code": code,
                "source": daily_source,
                "fetched_at": now_str(),
                "klines": klines,
            })
            mysql.save_klines(code, klines)
            ok_codes.append(code)
            logger.info("backfill %s: %s 条", code, len(klines))
        except Exception as e:
            logger.error("backfill %s 失败: %s", code, e)

    if refresh_stocks and ok_codes:
        from quant_system.tasks.stock_job import run_daily_stock
        logger.info("backfill 后刷新 stocks: %s", ", ".join(ok_codes))
        run_daily_stock(codes=ok_codes)
