"""Agent 上下文加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.storage.json_store import JsonStore


class StockContext:
    def __init__(self, code: str, store: JsonStore | None = None):
        self.code = code
        self.store = store or JsonStore(DBConfig())
        self.base = self.store.config.json_data_dir
        self.inputs_used: list[str] = []

    def _read(self, rel: str) -> dict[str, Any] | None:
        path = self.base / rel
        if not path.exists():
            return None
        self.inputs_used.append(rel)
        return self.store.read(path)

    @property
    def stock(self) -> dict[str, Any] | None:
        return self._read(f"stocks/{self.code}.json")

    @property
    def factors(self) -> dict[str, Any] | None:
        return self._read(f"factors/{self.code}.json")

    @property
    def signal(self) -> dict[str, Any] | None:
        return self._read(f"signals/{self.code}.json")

    @property
    def sentiment(self) -> dict[str, Any] | None:
        return self._read(f"sentiment/{self.code}.json")

    @property
    def enhance(self) -> dict[str, Any] | None:
        return self._read(f"enhance/{self.code}.json")

    @property
    def impact(self) -> dict[str, Any] | None:
        return self._read(f"impact/{self.code}.json")

    @property
    def prediction(self) -> dict[str, Any] | None:
        return self._read(f"predictions/{self.code}.json")

    @property
    def decision(self) -> dict[str, Any] | None:
        return self._read(f"decisions/{self.code}.json")

    def backtest(self, strategy: str = "ma_cross") -> dict[str, Any] | None:
        data = self._read(f"backtest/{self.code}_{strategy}.json")
        if data:
            return data
        # 回退：尝试另一种策略
        alt = "multi_factor" if strategy == "ma_cross" else "ma_cross"
        return self._read(f"backtest/{self.code}_{alt}.json")

    @property
    def quality(self) -> dict[str, Any] | None:
        latest = self._read("quality/latest.json")
        if not latest:
            return None
        for item in latest.get("stocks") or []:
            if item.get("code") == self.code:
                self.inputs_used.append("quality/latest.json")
                return item
        return None

    @property
    def name(self) -> str:
        stock = self.stock or {}
        return stock.get("name") or self.code

    @property
    def trade_date(self) -> str:
        stock = self.stock or {}
        return stock.get("trade_date") or ""
