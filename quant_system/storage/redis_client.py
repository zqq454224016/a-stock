"""Redis 缓存客户端。"""

from __future__ import annotations

import json
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class RedisClient:
    def __init__(self, config: DBConfig | None = None):
        self.config = config or DBConfig()
        self._client = None

    @property
    def enabled(self) -> bool:
        return self.config.redis_enabled

    def connect(self):
        if not self.enabled:
            return None
        try:
            import redis
            self._client = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
                password=self.config.redis_password,
                decode_responses=True,
            )
            self._client.ping()
            logger.info("Redis 已连接: %s", self.config.redis_host)
            return self._client
        except Exception as e:
            logger.warning("Redis 连接失败: %s", e)
            return None

    def set_json(self, key: str, data: Any, ttl: int = 3600) -> None:
        if not self._client:
            return
        self._client.setex(key, ttl, json.dumps(data, ensure_ascii=False))

    def get_json(self, key: str) -> Any | None:
        if not self._client:
            return None
        raw = self._client.get(key)
        return json.loads(raw) if raw else None
