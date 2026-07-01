"""舆情情绪模型（Phase 2 预留）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SentimentPost:
    code: str
    platform: str          # xueqiu / eastmoney / ths
    title: str
    content: str
    author: str
    publish_time: str
    likes: int = 0
    replies: int = 0
    heat: float = 0.0
    label: str = "中性"    # 看多/看空/中性

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
