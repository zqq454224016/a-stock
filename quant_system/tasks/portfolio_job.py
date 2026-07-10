"""组合管理与账户级风控任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.portfolio.analyzer import build_portfolio_payload
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _read_optional(store: JsonStore, rel: str) -> dict[str, Any] | None:
    path = store.config.json_data_dir / rel
    if not path.exists():
        return None
    try:
        return store.read(path)
    except Exception:
        return None


def _load_map(store: JsonStore, folder: str, index_key: str, fallback_glob: bool = True) -> dict[str, dict[str, Any]]:
    base = store.config.json_data_dir / folder
    rows: list[dict[str, Any]] = []
    index = _read_optional(store, f"{folder}/index.json")
    if index:
        rows = index.get(index_key) or index.get("items") or index.get("stocks") or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        payload = _read_optional(store, f"{folder}/{code}.json")
        if payload:
            out[code] = payload
    if fallback_glob and base.exists():
        for path in sorted(base.glob("*.json")):
            if path.stem == "index":
                continue
            out.setdefault(path.stem, store.read(path))
    return out


def run_portfolio_job() -> dict[str, Any]:
    store = JsonStore(DBConfig())
    account = _read_optional(store, "trading/account.json") or {}
    payload = build_portfolio_payload(
        account=account,
        stocks=_load_map(store, "stocks", "stocks"),
        decisions=_load_map(store, "decisions", "decisions"),
        factors=_load_map(store, "factors", "stocks"),
        enhances=_load_map(store, "enhance", "stocks"),
        impacts=_load_map(store, "impact", "items"),
        updated_at=now_str(),
    )
    store.save_portfolio(payload)
    summary = payload.get("summary") or {}
    logger.info(
        "组合分析完成: equity=%s cash_weight=%s positions=%s alerts=%s",
        summary.get("total_equity"), summary.get("cash_weight"), summary.get("position_count"), summary.get("risk_alert_count"),
    )
    return payload
