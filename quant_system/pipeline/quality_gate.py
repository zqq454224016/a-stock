"""质量门禁：因子 / 回测准入判断。"""

from __future__ import annotations

from typing import Any

from quant_system.config.factor_config import FACTOR_MIN_SCORE, QUALITY_OK, QUALITY_WARN
from quant_system.config.db_config import DBConfig
from quant_system.storage.json_store import JsonStore


def is_factor_eligible(quality: dict[str, Any]) -> bool:
    score = quality.get("quality_score", 0)
    return score >= FACTOR_MIN_SCORE and quality.get("status") != "error"


def is_backtest_eligible(quality: dict[str, Any], *, allow_warn: bool = False) -> bool:
    score = quality.get("quality_score", 0)
    if score >= QUALITY_OK:
        return True
    return allow_warn and score >= QUALITY_WARN


def factor_block_reason(quality: dict[str, Any]) -> str | None:
    if is_factor_eligible(quality):
        return None
    score = quality.get("quality_score", 0)
    if score < FACTOR_MIN_SCORE:
        return f"quality_score={score} < {FACTOR_MIN_SCORE}"
    return f"status={quality.get('status')}"


def load_quality_map(store: JsonStore | None = None) -> dict[str, dict[str, Any]]:
    store = store or JsonStore(DBConfig())
    path = store.quality_dir() / "latest.json"
    if not path.exists():
        return {}
    data = store.read(path)
    return {s["code"]: s for s in data.get("stocks", []) if s.get("code")}
