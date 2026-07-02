"""盘中实时采集任务（方案 A+B）。"""

from __future__ import annotations

import time
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.data_source.minute_api import MinuteAPI
from quant_system.pipeline.intraday_analyzer import build_intraday_analysis
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, to_symbol
from quant_system.storage.json_store import JsonStore
from quant_system.storage.redis_client import RedisClient
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str, today_str

logger = get_logger(__name__)


def run_intraday_live(codes: list[str] | None = None) -> list[dict]:
    """拉取自选股实时价 + 1/5 分钟 K，写入 assets/data/stocks/live/。"""
    cfg = CrawlerConfig()
    api = AkShareAPI(cfg)
    minute_api = MinuteAPI(api, cfg)
    store = JsonStore(DBConfig())
    redis = RedisClient(DBConfig())
    redis.connect()

    if codes:
        stocks = [{"code": normalize_code(c), "name": ""} for c in codes]
    else:
        stocks = load_watchlist(cfg)

    if not stocks:
        logger.error("未配置自选股，请编辑 assets/data/watchlist.json")
        return []

    codes_list = [normalize_code(s["code"]) for s in stocks]
    spot_map = api.fetch_spot_map(codes=codes_list)
    results: list[dict[str, Any]] = []

    for item in stocks:
        code = normalize_code(item["code"])
        name = item.get("name", "")
        symbol = to_symbol(code)
        try:
            logger.info("盘中采集 %s (%s)", code, name or symbol)
            minute_1m_raw = minute_api.fetch_minute(symbol, period="1")
            minute_1m, minute_date, minute_is_today = minute_api.filter_latest_session(minute_1m_raw)
            if not minute_is_today:
                logger.warning(
                    "分钟线非当日 %s: 分钟=%s 今日=%s，现价将使用 spot",
                    code, minute_date, today_str(),
                )
            try:
                minute_5m_raw = minute_api.fetch_minute(symbol, period="5")
                minute_5m, _, m5_today = minute_api.filter_latest_session(minute_5m_raw)
                if not m5_today:
                    minute_5m = None
            except Exception as e:
                logger.warning("5分钟线不可用 %s: %s", code, e)
                minute_5m = None

            live = build_intraday_analysis(
                code, name, spot_map.get(code), minute_1m, minute_5m,
                minute_trade_date=minute_date,
                minute_is_today=minute_is_today,
            )
            store.save_live_stock(code, live)
            redis.set_json(f"live:stock:{code}", live, ttl=cfg.live_redis_ttl)
            results.append({
                "code": code,
                "name": live["name"],
                "trade_date": live["trade_date"],
                "close": live["quote"]["close"],
                "change_pct": live["quote"]["change_pct"],
                "signal": live["intraday"]["signal"],
            })
        except Exception as e:
            logger.error("盘中采集 %s 失败: %s", code, e)

    if results:
        store.save_live_index(results, now_str())
    logger.info("intraday_live 完成，共 %s 只", len(results))
    return results


def run_intraday_snapshot() -> list[dict]:
    """调度器入口：盘中自选股实时快照。"""
    logger.info("intraday_snapshot 启动")
    return run_intraday_live()


def run_intraday_loop(interval_sec: int = 60, codes: list[str] | None = None) -> None:
    """开发用：循环盘中采集，Ctrl+C 退出。"""
    logger.info("盘中轮询启动，间隔 %ss", interval_sec)
    try:
        while True:
            run_intraday_live(codes=codes)
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        logger.info("盘中轮询已停止")
