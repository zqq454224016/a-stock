"""Phase 1 point-in-time market facts: universe, corporate actions and trading status."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.tickflow_api import TickFlowAPI
from quant_system.data_source.tushare_api import TushareAPI
from quant_system.tasks.universe_job import sync_tickflow_universe
from quant_system.utils.time_utils import now_str


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _validate_universe(rows: list[dict[str, Any]]) -> dict[str, Any]:
    codes = [str(row.get("code") or "") for row in rows]
    invalid = [code for code in codes if len(code) != 6 or not code.isdigit()]
    duplicates = len(codes) - len(set(codes))
    exchanges = sorted({str(row.get("exchange") or "") for row in rows})
    status = "valid" if rows and not invalid and duplicates == 0 and set(exchanges) == {"BJ", "SH", "SZ"} else "invalid"
    return {"status": status, "invalid_codes": len(invalid), "duplicate_codes": duplicates, "exchanges": exchanges}


def _iso_date(value: Any) -> str | None:
    text = str(value or "").replace("-", "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return None


def _security_master(
    universe: list[dict[str, Any]], supplement: dict[str, Any] | None, cfg: CrawlerConfig,
) -> dict[str, Any]:
    """Persist listed and non-listed securities separately from today's tradable universe."""
    merged: dict[str, dict[str, Any]] = {}
    for row in universe:
        merged[row["symbol"]] = {
            "symbol": row["symbol"], "code": row["code"], "name": row.get("name"),
            "exchange": row.get("exchange"), "market": None, "list_status": "L",
            "list_date": _iso_date(row.get("listing_date")), "delist_date": None,
            "effective_from": _iso_date(row.get("listing_date")), "effective_to": None,
            "sources": ["tickflow"],
        }
    for row in (supplement or {}).get("securities") or []:
        symbol = str(row.get("ts_code") or "")
        code = str(row.get("symbol") or symbol.split(".", 1)[0])
        if not symbol or len(code) != 6:
            continue
        current = merged.setdefault(symbol, {"symbol": symbol, "code": code, "sources": []})
        current.update({
            "name": row.get("name") or current.get("name"),
            "exchange": {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(str(row.get("exchange")), row.get("exchange")),
            "market": row.get("market"), "list_status": row.get("list_status"),
            "list_date": _iso_date(row.get("list_date")), "delist_date": _iso_date(row.get("delist_date")),
            "effective_from": _iso_date(row.get("list_date")),
            "effective_to": _iso_date(row.get("delist_date")),
        })
        current["sources"] = sorted(set((current.get("sources") or []) + ["tushare"]))
    items = sorted(merged.values(), key=lambda item: item["symbol"])
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("list_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    payload = {
        "dataset": "market.instruments", "schema_version": "1.0.0", "updated_at": now_str(),
        "source": "tickflow+tushare" if supplement else "tickflow",
        "status": "available", "count": len(items), "list_status_counts": status_counts,
        "point_in_time_note": "Use list_date/delist_date; do not substitute today's listed universe in backtests.",
        "items": items,
    }
    _write(cfg.data_dir / "normalized" / "market.instruments" / "security_master.json", payload)
    return payload


def _merge_status_events(incoming: dict[str, Any], cfg: CrawlerConfig) -> dict[str, Any]:
    path = cfg.data_dir / "normalized" / "market.trading_status" / "events.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": []}
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in previous.get("items") or []:
        key = (str(item.get("symbol")), str(item.get("trade_date")), str(item.get("event_type")))
        records[key] = item
    for source_key, event_prefix in (("suspension_events", "trading"), ("st_daily", "risk_warning")):
        for row in incoming.get(source_key) or []:
            compact = str(row.get("trade_date") or "")
            trade_date = _iso_date(compact)
            symbol = str(row.get("ts_code") or "")
            subtype = str(row.get("suspend_type") or row.get("type") or "")
            if not symbol or not trade_date:
                continue
            event_type = f"{event_prefix}.{subtype or 'observed'}"
            records[(symbol, trade_date, event_type)] = {
                "symbol": symbol, "trade_date": trade_date, "event_type": event_type,
                "name": row.get("name"), "type_name": row.get("type_name"),
                "suspend_timing": row.get("suspend_timing"), "source": "tushare",
                "known_at": f"{trade_date}T15:00:00+08:00",
            }
    items = sorted(records.values(), key=lambda item: (item["trade_date"], item["symbol"], item["event_type"]))
    payload = {
        "dataset": "market.trading_status.events", "schema_version": "1.0.0",
        "updated_at": now_str(), "source": "tushare", "status": "partial" if incoming.get("errors") else "available",
        "coverage_start": items[0]["trade_date"] if items else None,
        "coverage_end": items[-1]["trade_date"] if items else None,
        "count": len(items), "source_errors": incoming.get("errors") or {}, "items": items,
    }
    _write(path, payload)
    return payload


def _update_status_history(items: list[dict[str, Any]], cfg: CrawlerConfig) -> Path:
    path = cfg.data_dir / "normalized" / "market.trading_status" / "history.json"
    today = date.today().isoformat()
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": []}
    histories: dict[str, list[dict[str, Any]]] = {}
    for row in previous.get("items") or []:
        histories.setdefault(row["symbol"], []).append(row)
    fields = ("is_st", "is_suspended", "limit_up", "limit_down", "list_status", "delist_date")
    for item in items:
        symbol = item["symbol"]
        state = {key: item.get(key) for key in fields}
        periods = histories.setdefault(symbol, [])
        if periods and all(periods[-1].get(key) == state[key] for key in fields):
            periods[-1]["observed_through"] = today
            continue
        periods.append({
            "symbol": symbol,
            "name": item.get("name"),
            "observed_from": today,
            "observed_through": today,
            **state,
            "source": item.get("source") or "tickflow",
            "history_semantics": "observed_by_this_system_not_backfilled",
        })
    flattened = [period for periods in histories.values() for period in periods]
    return _write(path, {
        "dataset": "market.trading_status.history",
        "schema_version": "1.0.0",
        "updated_at": now_str(),
        "count": len(flattened),
        "limitations": ["history_starts_at_first_local_observation", "historical_backfill_requires_date_range_run"],
        "items": flattened,
    })


def _trading_status_snapshot(
    rows: list[dict[str, Any]], cfg: CrawlerConfig, supplement: dict[str, Any] | None = None,
) -> Path:
    snapshot_date = str((supplement or {}).get("trade_date") or date.today().isoformat())
    supplement = supplement or {}
    suspended = {str(row.get("ts_code") or "") for row in supplement.get("suspended") or []}
    st_codes = {str(row.get("ts_code") or "") for row in supplement.get("st") or []}
    securities = {str(row.get("ts_code") or ""): row for row in supplement.get("securities") or []}
    items = [{
        "symbol": row["symbol"],
        "code": row["code"],
        "name": row["name"],
        "exchange": row["exchange"],
        "trade_date": snapshot_date,
        "is_st": row["symbol"] in st_codes if "st" in supplement and not supplement.get("errors", {}).get("st") else bool(row.get("is_st")),
        "is_suspended": row["symbol"] in suspended if "suspended" in supplement and not supplement.get("errors", {}).get("suspended") else None,
        "limit_up": row.get("limit_up"),
        "limit_down": row.get("limit_down"),
        "listing_date": (securities.get(row["symbol"]) or {}).get("list_date") or row.get("listing_date") or None,
        "list_status": (securities.get(row["symbol"]) or {}).get("list_status") or "L",
        "delist_date": (securities.get(row["symbol"]) or {}).get("delist_date") or None,
        "source": "tickflow+tushare" if supplement else "tickflow",
        "known_at": now_str(),
    } for row in rows]
    path = _write(cfg.data_dir / "normalized" / "market.trading_status" / f"{snapshot_date}.json", {
        "dataset": "market.trading_status",
        "schema_version": "1.0.0",
        "trade_date": snapshot_date,
        "source": "tickflow+tushare" if supplement else "tickflow",
        "count": len(items),
        "quality": {
            "status": "valid" if supplement and not supplement.get("errors") else "partial",
            "limitations": list((supplement.get("errors") or {}).values()) if supplement else ["tushare_supplement_not_configured"],
        },
        "items": items,
    })
    _update_status_history(items, cfg)
    return path


def _sync_ex_factors(api: TickFlowAPI, symbols: list[str], cfg: CrawlerConfig) -> dict[str, Any]:
    output = cfg.data_dir / "normalized" / "market.corporate_actions" / "ex_factors.json"
    try:
        rows = api.fetch_ex_factors(symbols)
        payload = {
            "dataset": "market.corporate_actions",
            "schema_version": "1.0.0",
            "source": "tickflow",
            "updated_at": now_str(),
            "status": "available",
            "count": len(rows),
            "items": rows,
        }
    except Exception as exc:  # provider tier is an explicit dataset state
        try:
            rows = TushareAPI(cfg).fetch_latest_ex_factors()
            payload = {
                "dataset": "market.corporate_actions", "schema_version": "1.0.0",
                "source": "tushare", "fallback_from": "tickflow", "updated_at": now_str(),
                "status": "available" if rows else "unavailable", "coverage": "latest_market_snapshot",
                "count": len(rows), "primary_error": str(exc), "items": rows,
            }
        except Exception as fallback_exc:
            payload = {
                "dataset": "market.corporate_actions", "schema_version": "1.0.0",
                "source": "tickflow", "updated_at": now_str(), "status": "unavailable",
                "count": 0, "error": str(exc), "fallback_error": str(fallback_exc), "items": [],
            }
    _write(output, payload)
    return payload


def run_phase1_market_data(codes: list[str] | None = None) -> dict[str, Any]:
    cfg = CrawlerConfig()
    universe = sync_tickflow_universe(cfg)
    universe_quality = _validate_universe(universe)
    if universe_quality["status"] != "valid":
        raise RuntimeError(f"Universe quality gate failed: {universe_quality}")
    supplement: dict[str, Any] | None = None
    if cfg.tushare_enabled and cfg.tushare_token:
        tushare = TushareAPI(cfg)
        supplement = tushare.fetch_market_status(date.today().isoformat())
        _write(cfg.data_dir / "raw" / "tushare" / "market_status" / f"{date.today().isoformat()}.json", supplement)
        history_start = (date.today() - timedelta(days=max(1, cfg.market_status_backfill_days))).isoformat()
        history = tushare.fetch_status_history(history_start, date.today().isoformat())
        _write(cfg.data_dir / "raw" / "tushare" / "market_status_history" / f"{date.today().isoformat()}.json", history)
        status_events = _merge_status_events(history, cfg)
    else:
        status_events = {"status": "unavailable", "count": 0, "reason": "tushare_not_configured"}
    security_master = _security_master(universe, supplement, cfg)
    status_path = _trading_status_snapshot(universe, cfg, supplement)
    selected = codes or [row["code"] for row in universe]
    factors = _sync_ex_factors(TickFlowAPI(cfg), selected, cfg)
    summary = {
        "phase": "phase1_market_data",
        "updated_at": now_str(),
        "universe_count": len(universe),
        "universe_quality": universe_quality,
        "universe_snapshot": str(cfg.data_dir / "universe" / "snapshots" / f"{date.today().isoformat()}.json"),
        "security_master": str(cfg.data_dir / "normalized" / "market.instruments" / "security_master.json"),
        "security_master_count": security_master["count"],
        "list_status_counts": security_master["list_status_counts"],
        "trading_status_snapshot": str(status_path),
        "market_status_supplement": "tushare" if supplement else "not_configured",
        "market_status_errors": (supplement or {}).get("errors", {}),
        "status_events_status": status_events["status"],
        "status_events_count": status_events["count"],
        "ex_factors_status": factors["status"],
        "ex_factors_count": factors["count"],
    }
    _write(cfg.data_dir / "manifests" / "phase1_market_data.json", summary)
    return summary
