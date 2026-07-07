"""盘中实时采集任务（方案 A+B）。"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.data_source.minute_api import MinuteAPI
from quant_system.pipeline.intraday_analyzer import build_intraday_analysis
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, to_symbol
from quant_system.storage.json_store import JsonStore
from quant_system.storage.redis_client import RedisClient
from quant_system.utils.concurrent_fetch import run_parallel_map
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str, today_str

logger = get_logger(__name__)


def _cached_spot_from_stock(store: JsonStore, code: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / "stocks" / f"{code}.json"
    if not path.exists():
        return None
    data = store.read(path)
    quote = data.get("quote") or {}
    if quote.get("close") is None:
        return None
    return {
        **quote,
        "name": data.get("name", quote.get("name", "")),
        "quote_source": "stock_cache",
    }


def _cached_live_from_disk(store: JsonStore, code: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / "stocks" / "live" / f"{code}.json"
    if not path.exists():
        return None
    return store.read(path)


def _fetch_minutes_safe(
    minute_api: MinuteAPI,
    symbol: str,
    code: str,
) -> tuple[pd.DataFrame, str, bool, pd.DataFrame | None]:
    minute_1m = pd.DataFrame()
    minute_date = ""
    minute_is_today = False
    minute_5m: pd.DataFrame | None = None

    try:
        minute_1m_raw = minute_api.fetch_minute(symbol, period="1")
        minute_1m, minute_date, minute_is_today = minute_api.filter_latest_session(minute_1m_raw)
        if not minute_is_today:
            logger.warning(
                "分钟线非当日 %s: 分钟=%s 今日=%s，现价将使用 spot",
                code, minute_date, today_str(),
            )
    except Exception as e:
        logger.warning("1分钟线不可用 %s: %s", code, e)

    if not minute_api._sina_disabled:
        try:
            minute_5m_raw = minute_api.fetch_minute(symbol, period="5")
            minute_5m, _, m5_today = minute_api.filter_latest_session(minute_5m_raw)
            if not m5_today:
                minute_5m = None
        except Exception as e:
            logger.warning("5分钟线不可用 %s: %s", code, e)

    return minute_1m, minute_date, minute_is_today, minute_5m


def _process_intraday_stock(
    item: dict[str, Any],
    api: AkShareAPI,
    minute_api: MinuteAPI,
    store: JsonStore,
    redis: RedisClient,
    cfg: CrawlerConfig,
    spot_map: dict[str, dict],
) -> dict[str, Any] | None:
    code = normalize_code(item["code"])
    name = item.get("name", "")
    symbol = to_symbol(code)
    try:
        logger.info("盘中采集 %s (%s)", code, name or symbol)
        spot = spot_map.get(code)
        if not spot:
            logger.warning("无实时行情 %s，尝试缓存", code)

        minute_1m, minute_date, minute_is_today, minute_5m = _fetch_minutes_safe(
            minute_api, symbol, code,
        )

        if minute_1m.empty and not spot:
            cached_live = _cached_live_from_disk(store, code)
            if cached_live:
                cached_live["updated_at"] = now_str()
                store.save_live_stock(code, cached_live)
                redis.set_json(f"live:stock:{code}", cached_live, ttl=cfg.live_redis_ttl)
                logger.warning("使用盘中缓存 %s", code)
                return {
                    "code": code,
                    "name": cached_live.get("name", name),
                    "trade_date": cached_live.get("trade_date"),
                    "close": (cached_live.get("quote") or {}).get("close"),
                    "change_pct": (cached_live.get("quote") or {}).get("change_pct"),
                    "signal": (cached_live.get("intraday") or {}).get("signal"),
                }

        live = build_intraday_analysis(
            code, name, spot, minute_1m, minute_5m,
            minute_trade_date=minute_date,
            minute_is_today=minute_is_today,
        )
        store.save_live_stock(code, live)
        redis.set_json(f"live:stock:{code}", live, ttl=cfg.live_redis_ttl)
        return {
            "code": code,
            "name": live["name"],
            "trade_date": live["trade_date"],
            "close": live["quote"]["close"],
            "change_pct": live["quote"]["change_pct"],
            "signal": live["intraday"]["signal"],
        }
    except Exception as e:
        logger.error("盘中采集 %s 失败: %s", code, e)
        return None


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
    try:
        spot_map = api.fetch_spot_map(codes=codes_list)
    except Exception as e:
        logger.error("实时行情不可用: %s", e)
        spot_map = {}

    for code in codes_list:
        if code not in spot_map:
            cached = _cached_spot_from_stock(store, code)
            if cached:
                spot_map[code] = cached
                logger.warning("使用日线缓存行情 %s", code)

    worker = lambda item: _process_intraday_stock(
        item, api, minute_api, store, redis, cfg, spot_map,
    )
    results = run_parallel_map(
        stocks,
        worker,
        max_workers=cfg.fetch_workers,
        label="盘中采集",
    )
    index = [r for r in results if r is not None]

    if index:
        store.save_live_index(index, now_str())
    logger.info("盘中采集完成，共 %s 只", len(index))
    return index


def run_intraday_snapshot() -> list[dict]:
    """调度器入口：盘中自选股实时快照。"""
    logger.info("盘中快照启动")
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
