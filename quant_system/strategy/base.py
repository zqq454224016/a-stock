"""策略基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseStrategy(ABC):
    name: str = "base"
    version: str = "1.0.0"

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        为每根 K 线生成信号列：
        - signal: 1=买入, -1=卖出, 0=持有/观望
        信号在当日收盘后产生，下一交易日开盘撮合。
        """

    def meta(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version}
