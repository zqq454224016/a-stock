"""Build normalized historical suspension/ST/corporate-action events with confidence."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.strategy_job import _write
from quant_system.utils.time_utils import now_str


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _gzip_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _gzip_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
    temporary.replace(path)


def run_market_event_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    regime = _read(cfg.data_dir / "market_regime/five_year.json")
    calendar = sorted(str(row.get("date"))[:10] for row in regime.get("items") or [] if row.get("date"))
    events: list[dict[str, Any]] = []
    by_code: dict[str, list[dict[str, Any]]] = {}
    inferred_suspensions = explicit_suspensions = corporate_actions = 0

    for raw_path in sorted((cfg.data_dir / "raw_history").glob("*.json.gz")):
        code = raw_path.name.split(".", 1)[0]
        raw_rows = _gzip_rows(raw_path)
        execution_rows = _gzip_rows(cfg.data_dir / "execution_history" / f"{code}.json.gz")
        dates = {str(row.get("date") or row.get("trade_date"))[:10] for row in raw_rows}
        if not dates:
            continue
        first, last = min(dates), max(dates)
        rows: list[dict[str, Any]] = []
        for date in calendar:
            if first <= date <= last and date not in dates:
                rows.append({
                    "code": code, "date": date, "event_type": "suspension",
                    "state": "suspended", "source": "market_calendar_minus_raw_daily",
                    "confidence": "medium", "known_at": date,
                })
                inferred_suspensions += 1
        for row in raw_rows:
            if float(row.get("volume") or 0) <= 0:
                date = str(row.get("date") or row.get("trade_date"))[:10]
                rows.append({
                    "code": code, "date": date, "event_type": "suspension",
                    "state": "suspended", "source": "raw_daily_zero_volume",
                    "confidence": "high", "known_at": date,
                })
                explicit_suspensions += 1
        for row in execution_rows:
            if row.get("corporate_action_inferred"):
                date = str(row.get("date"))[:10]
                rows.append({
                    "code": code, "date": date, "event_type": "corporate_action",
                    "state": "adjustment_ratio_changed", "source": "raw_qfq_ratio_change",
                    "confidence": "high", "known_at": date,
                    "adjustment_ratio": row.get("adjustment_ratio"),
                })
                corporate_actions += 1
        rows.sort(key=lambda item: (item["date"], item["event_type"]))
        _gzip_write(cfg.data_dir / "market_events/by_code" / f"{code}.json.gz", rows)
        by_code[code] = rows
        events.extend(rows)

    # Snapshot evidence can only establish observed state, not historical start/end.
    st_observations: list[dict[str, Any]] = []
    for snapshot in sorted((cfg.data_dir / "universe/snapshots").glob("*.json")):
        payload = _read(snapshot)
        observed_date = snapshot.stem
        for row in payload.get("stocks") or payload.get("items") or []:
            if row.get("is_st") or "ST" in str(row.get("name") or "").upper():
                st_observations.append({
                    "code": str(row.get("code") or ""), "date": observed_date,
                    "event_type": "st_observation", "state": "st",
                    "source": "security_master_snapshot", "confidence": "high",
                    "known_at": observed_date,
                })
    st_change_payload = _read(cfg.data_dir / "market_events/st_changes_sz.json")
    st_changes = list(st_change_payload.get("events") or [])
    sse_payload = _read(cfg.data_dir / "market_events/sse/events.json")
    sse_changes = list(sse_payload.get("events") or [])
    _gzip_write(cfg.data_dir / "market_events/events.json.gz", events + st_observations + st_changes + sse_changes)
    payload = {
        "status": "complete" if sse_payload.get("status") == "complete" and st_change_payload else "partial",
        "updated_at": now_str(), "calendar_days": len(calendar),
        "stocks": len(by_code), "event_count": len(events) + len(st_observations) + len(st_changes) + len(sse_changes),
        "counts": {
            "suspension_inferred": inferred_suspensions,
            "suspension_explicit": explicit_suspensions,
            "corporate_action_inferred": corporate_actions,
            "st_observations": len(st_observations),
            "st_status_changes_sz": len(st_changes),
            "st_status_changes_sh": len(sse_changes),
        },
        "source_policy": {
            "python": "structured acquisition and deterministic inference",
            "ai": "source discovery and announcement exception parsing only",
            "verification": "official exchange announcements and public structured sources",
        },
        "blockers": [
            "公告标题与PDF规则已覆盖当前五年沪市主板；更早历史不在当前回测窗口",
        ],
    }
    _write(cfg.data_dir / "market_events/status.json", payload)
    return payload


if __name__ == "__main__":
    run_market_event_job()
