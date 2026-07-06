"""因子任务辅助。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.factors.composite import build_composite_factors
from quant_system.storage.json_store import JsonStore


def load_sentiment_factors(code: str, store: JsonStore | None = None) -> dict[str, Any] | None:
    store = store or JsonStore(DBConfig())
    path = store.sentiment_dir() / f"{code}.json"
    if not path.exists():
        return None
    data = store.read(path)
    return data.get("factors")


def load_enhance_data(code: str, store: JsonStore | None = None) -> dict[str, Any] | None:
    store = store or JsonStore(DBConfig())
    path = store.enhance_dir() / f"{code}.json"
    if not path.exists():
        return None
    return store.read(path)


def save_composite_factors(
    code: str,
    trade_date: str,
    technical_payload: dict[str, Any],
    store: JsonStore | None = None,
) -> dict[str, Any]:
    store = store or JsonStore(DBConfig())
    sentiment = load_sentiment_factors(code, store)
    enhance = load_enhance_data(code, store)
    composite = build_composite_factors(
        code,
        trade_date,
        technical_payload["factors"],
        sentiment=sentiment,
        enhance=enhance,
        data_version=technical_payload.get("data_version"),
        technical_version=technical_payload.get("factor_version"),
        sentiment_version=(sentiment or {}).get("sentiment_version") if sentiment else None,
        enhance_version=(enhance or {}).get("version") if enhance else None,
    )
    store.save_factors(code, composite)
    return composite
