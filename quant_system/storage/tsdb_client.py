"""时序数据库客户端（未来扩展）。"""

from __future__ import annotations

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class TSDBClient:
    def __init__(self, config: DBConfig | None = None):
        self.config = config or DBConfig()

    @property
    def enabled(self) -> bool:
        return self.config.tsdb_enabled

    def write_klines(self, code: str, klines: list[dict]) -> None:
        if not self.enabled:
            return
        logger.info("TSDB write_klines 预留，code=%s", code)
