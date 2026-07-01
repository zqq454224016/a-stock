"""MySQL 存储客户端。"""

from __future__ import annotations

import json
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class MySQLClient:
    def __init__(self, config: DBConfig | None = None):
        self.config = config or DBConfig()
        self._engine = None

    @property
    def enabled(self) -> bool:
        return self.config.mysql_enabled

    def connect(self):
        if not self.enabled:
            logger.info("MySQL 未启用，使用 JSON 降级存储")
            return None
        try:
            from sqlalchemy import create_engine
            self._engine = create_engine(self.config.mysql_url, pool_pre_ping=True)
            logger.info("MySQL 已连接: %s", self.config.mysql_host)
            return self._engine
        except ImportError:
            logger.warning("sqlalchemy/pymysql 未安装，跳过 MySQL")
            return None

    def save_market_snapshot(self, data: dict[str, Any]) -> None:
        if not self._engine:
            return
        # 预留：写入 market_daily 表
        logger.info("MySQL save_market_snapshot 预留，trade_date=%s", data.get("trade_date"))

    def save_klines(self, code: str, klines: list[dict]) -> None:
        if not self._engine:
            return
        logger.info("MySQL save_klines 预留，code=%s rows=%s", code, len(klines))
