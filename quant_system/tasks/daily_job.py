"""每日行情采集任务。"""

from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.validator import validate_market_snapshot
from quant_system.storage.json_store import JsonStore
from quant_system.storage.mysql_client import MySQLClient
from quant_system.storage.redis_client import RedisClient
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def run_daily_market(mock: bool = False) -> dict:
    store = JsonStore(DBConfig())
    mysql = MySQLClient(DBConfig())
    redis = RedisClient(DBConfig())
    mysql.connect()
    redis.connect()

    if mock:
        logger.info("daily_market: mock 模式")
        data = store.load_mock_market()
    else:
        api = AkShareAPI(CrawlerConfig())
        try:
            data = api.fetch_market_snapshot(store=store)
            validate_market_snapshot(data)
        except Exception as e:
            from quant_system.utils.time_utils import now_str
            logger.error("大盘采集失败，使用缓存降级: %s", e)
            data = store.load_mock_market()
            data["updated_at"] = now_str()
            data["degraded"] = True
            data.setdefault("limitations", []).append("market_fetch_failed")
            validate_market_snapshot(data)

    store.save_market_snapshot(data)
    mysql.save_market_snapshot(data)
    redis.set_json("market:latest", data, ttl=7200)

    logger.info(
        "daily_market 完成: %s, 指数 %s, 涨幅榜首 %s%s",
        data["trade_date"],
        len(data.get("indices", [])),
        data["top_gainers"][0]["name"] if data.get("top_gainers") else "-",
        f" [降级: {','.join(data.get('limitations') or [])}]" if data.get("degraded") else "",
    )
    return data
