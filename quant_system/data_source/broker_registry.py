"""券商/行情软件数据源注册表（同花顺、长江e号等）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["market", "fundamental", "trade"]
SourceStatus = Literal["active", "planned", "disabled"]


@dataclass(frozen=True)
class BrokerSourceMeta:
    key: str
    name: str
    kind: SourceKind
    status: SourceStatus
    description: str
    env_hint: str = ""


# 行情/基本面类软件（非交易接口）
DATA_SOURCES: dict[str, BrokerSourceMeta] = {
    "eastmoney": BrokerSourceMeta(
        "eastmoney", "东方财富", "market", "active", "全市场/盘口/日K/资金流",
    ),
    "sina": BrokerSourceMeta(
        "sina", "新浪财经", "market", "active", "全市场/分钟线/日K",
    ),
    "tencent": BrokerSourceMeta(
        "tencent", "腾讯财经", "market", "active", "日K备用",
    ),
    "ths": BrokerSourceMeta(
        "ths", "同花顺", "fundamental", "active", "行业板块/财务摘要/盈利预测",
    ),
    "xueqiu": BrokerSourceMeta(
        "xueqiu", "雪球", "market", "active", "个股实时价/舆情热榜",
    ),
    "changjiang": BrokerSourceMeta(
        "changjiang",
        "长江e号",
        "trade",
        "planned",
        "需券商官方 OpenAPI / QMT / Ptrade 接入，当前仅注册占位",
        env_hint="CHANGJIANG_API_URL + CHANGJIANG_API_TOKEN",
    ),
    "htsc": BrokerSourceMeta(
        "htsc",
        "华泰涨乐财富通",
        "trade",
        "planned",
        "需券商官方接口，当前仅注册占位",
        env_hint="HTSC_API_URL + HTSC_API_TOKEN",
    ),
}


def parse_enabled_data_sources() -> list[str]:
    """CRAWLER_EXTRA_SOURCES=ths,xueqiu,tencent"""
    raw = os.getenv("CRAWLER_EXTRA_SOURCES", "ths,xueqiu,tencent")
    keys = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return [k for k in keys if k in DATA_SOURCES and DATA_SOURCES[k].status == "active"]


def list_sources() -> list[dict]:
    return [
        {
            "key": m.key,
            "name": m.name,
            "kind": m.kind,
            "status": m.status,
            "description": m.description,
            "env_hint": m.env_hint,
        }
        for m in DATA_SOURCES.values()
    ]
