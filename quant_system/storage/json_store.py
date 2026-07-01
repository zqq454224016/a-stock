"""JSON 文件存储（本地默认）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


class JsonStore:
    def __init__(self, config: DBConfig | None = None):
        self.config = config or DBConfig()

    def write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("JSON 已写入 %s", path)

    def read(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def save_market_snapshot(self, data: dict[str, Any]) -> Path:
        path = self.config.json_data_dir / "latest.json"
        self.write(path, data)
        return path

    def save_stock_analysis(self, code: str, data: dict[str, Any]) -> Path:
        path = self.config.json_data_dir / "stocks" / f"{code}.json"
        self.write(path, data)
        return path

    def save_stock_index(self, stocks: list[dict], updated_at: str) -> Path:
        path = self.config.json_data_dir / "stocks" / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": stocks})
        return path

    def live_dir(self) -> Path:
        return self.config.json_data_dir / "stocks" / "live"

    def save_live_stock(self, code: str, data: dict[str, Any]) -> Path:
        path = self.live_dir() / f"{code}.json"
        self.write(path, data)
        return path

    def save_live_index(self, stocks: list[dict], updated_at: str) -> Path:
        path = self.live_dir() / "index.json"
        self.write(path, {"updated_at": updated_at, "stocks": stocks})
        return path

    def load_mock_market(self) -> dict[str, Any]:
        path = self.config.json_data_dir / "latest.json"
        if path.exists():
            data = self.read(path)
            from quant_system.utils.time_utils import now_str
            data["updated_at"] = now_str()
            return data
        return {
            "trade_date": "",
            "indices": [],
            "market_distribution": [],
            "top_gainers": [],
            "top_losers": [],
            "industries": [],
            "fund_flow": {},
            "updated_at": "",
        }
