"""数据库配置（MySQL / Redis / TSDB）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class DBConfig:
    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "a_stock")
    mysql_enabled: bool = os.getenv("MYSQL_ENABLED", "0") == "1"

    redis_host: str = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_password: str | None = os.getenv("REDIS_PASSWORD") or None
    redis_enabled: bool = os.getenv("REDIS_ENABLED", "0") == "1"

    tsdb_url: str = os.getenv("TSDB_URL", "")
    tsdb_enabled: bool = os.getenv("TSDB_ENABLED", "0") == "1"

    # 本地 JSON 降级存储
    json_data_dir: Path = PROJECT_ROOT / "assets" / "data"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )
