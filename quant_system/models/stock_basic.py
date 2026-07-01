"""股票基础信息模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StockBasic:
    code: str
    name: str
    symbol: str = ""
    market: str = ""       # SH/SZ/BJ
    industry: str = ""
    list_date: str = ""
    is_st: bool = False
    status: str = "active"  # active/suspended/delisted

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StockBasic":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})
