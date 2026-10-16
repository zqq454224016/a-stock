"""多周期股票推荐任务。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.recommendation.builder import build_recommendation_payload
from quant_system.storage.json_store import JsonStore
from quant_system.utils.logger import get_logger
from quant_system.tasks.strategy_job import validation_calibration

logger = get_logger(__name__)


def _read(store: JsonStore, rel: str) -> dict[str, Any]:
    path = store.config.json_data_dir / rel
    if not path.exists():
        return {}
    try:
        return store.read(path)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("跳过损坏数据产物 %s: %s", path, exc)
        return {}


def _load_map(store: JsonStore, folder: str) -> dict[str, dict[str, Any]]:
    base = store.config.json_data_dir / folder
    if not base.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(base.glob("*.json")):
        if path.stem == "index":
            continue
        payload = _read(store, f"{folder}/{path.name}")
        if payload:
            rows[path.stem] = payload
    return rows


def _load_sector_data(store: JsonStore) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    root = store.config.json_data_dir / "sector_data"
    mapping_payload = _read(store, "sector_data/stock_industry_map.json")
    mapping = mapping_payload.get("stocks") or {}
    sectors = []
    for path in sorted((root / "history").glob("*.json")):
        try:
            payload = store.read(path)
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("rows") or []
        if len(rows) < 2:
            continue
        latest, previous = rows[-1], rows[-2]
        change = latest.get("change_pct")
        if change is None:
            old, new = float(previous.get("close") or 0), float(latest.get("close") or 0)
            change = (new / old - 1) * 100 if old > 0 else None
        if change is not None:
            sectors.append({
                "name": payload.get("industry") or path.stem,
                "change_pct": round(float(change), 2),
                "trade_date": latest.get("date"),
            })
    return sectors, mapping


def _load_daily_snapshots(store: JsonStore, trade_date: str | None) -> dict[str, dict[str, Any]]:
    snapshots = _load_map(store, "today_change")
    quotes = _read(store, "normalized/market.quotes.tencent/latest.json")
    if trade_date and str(quotes.get("trade_date") or "") != str(trade_date):
        return snapshots
    for quote in quotes.get("items") or []:
        code = str(quote.get("code") or "")
        if not code:
            continue
        row = dict(snapshots.get(code) or {})
        row.update({
            "close": quote.get("price", row.get("close")),
            "change_pct": quote.get("change_pct", row.get("change_pct")),
            "turnover_pct": quote.get("turnover_pct"),
            "float_cap_yi": quote.get("float_market_cap_yi"),
        })
        snapshots[code] = row
    intraday = _read(store, "daily_filter_intraday/latest.json")
    if not trade_date or str(intraday.get("trade_date") or "") == str(trade_date):
        market_checks = intraday.get("market_checks") or {}
        for code, checks in (intraday.get("stocks") or {}).items():
            row = dict(snapshots.get(code) or {})
            row["intraday_checks"] = {**market_checks, **checks}
            snapshots[code] = row
    return snapshots


def run_recommendation_job(limit: int = 5) -> dict[str, Any]:
    store = JsonStore(DBConfig())
    market = _read(store, "latest.json")
    sectors, sector_mapping = _load_sector_data(store)
    if sectors:
        market = dict(market)
        market["sector_market"] = {"scope": "full", "rows": sectors}
    latest_session = _read(store, "today_change/summary.json")
    latest_trade_date = latest_session.get("trade_date") or latest_session.get("latest_observed_trade_date")
    if latest_trade_date:
        market = dict(market)
        if not sectors:
            market["sector_market"] = {
                "scope": "leaderboard_only",
                "rows": list(latest_session.get("leading_industries") or []) + list(
                    latest_session.get("lagging_industries") or []
                ),
            }
        snapshot_trade_date = market.get("trade_date")
        market["trade_date"] = latest_trade_date
        market["context_dates"] = {
            "stock_breadth": latest_trade_date,
            "market_snapshot": snapshot_trade_date,
        }
        if snapshot_trade_date and str(snapshot_trade_date) < str(latest_trade_date):
            # Do not silently mix stale index/fund values into a newer stock session.
            market["indices"] = []
            market["fund_flow"] = {}
            market["degraded"] = True
            market["limitations"] = list(dict.fromkeys(
                list(market.get("limitations") or []) + ["index_and_fund_flow_older_than_stock_session"],
            ))
    strategies = _load_map(store, "strategy")
    selectors = {
        code: {
            "name": item.get("name"), "upside_score": item.get("trend_score"),
            "status": "candidate" if item.get("trend_stage") in {"rising", "recovery"} and float(item.get("trend_score") or 0) >= 65 else "watch",
            "risks": item.get("limitations") or [],
            "next_triggers": ["趋势阶段或五年验证结果发生变化时重新评估"],
        }
        for code, item in strategies.items() if item.get("status") == "analyzed"
    }
    predictions = {
        code: {
            "direction": ((item.get("outlook") or {}).get("20d") or {}).get("direction", "neutral"),
            "probability": max(0.5, min(0.9, float(item.get("trend_score") or 50) / 100)),
            "status": "strategy_derived",
        }
        for code, item in strategies.items() if item.get("status") == "analyzed"
    }
    strategy_validations = {
        code: converted for code, payload in _load_map(store, "strategy_backtest").items()
        if (converted := validation_calibration(payload))
    }
    payload = build_recommendation_payload(
        market=market,
        stocks=_load_map(store, "stocks"),
        selectors=selectors,
        predictions=predictions,
        factors=_load_map(store, "factors"),
        impacts=_load_map(store, "impact"),
        enhances=_load_map(store, "enhance"),
        replays=strategy_validations,
        daily_snapshots=_load_daily_snapshots(store, market.get("trade_date")),
        sector_mapping=sector_mapping,
        limit=limit,
    )
    store.save_recommendations(payload)
    counts = {key: len(value["recommendations"]) for key, value in payload["periods"].items()}
    logger.info("多周期推荐完成: %s", counts)
    return payload
