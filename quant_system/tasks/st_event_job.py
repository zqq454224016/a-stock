"""Acquire dated historical ST name changes from public exchange datasets."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.strategy_job import _write
from quant_system.utils.time_utils import now_str


def _is_st(value: Any) -> bool:
    text = str(value or "").upper()
    return "ST" in text or "风险警示" in text


def run_st_event_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    output_path = cfg.data_dir / "market_events/st_changes_sz.json"
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
            if str(previous.get("updated_at") or "").startswith(date.today().isoformat()):
                return {**previous, "status": "up_to_date"}
        except (OSError, ValueError):
            pass
    import akshare as ak

    frame = ak.stock_info_sz_change_name(symbol="简称变更")
    events: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        code = str(row.get("证券代码") or "").zfill(6)
        before, after = row.get("变更前简称"), row.get("变更后简称")
        before_st, after_st = _is_st(before), _is_st(after)
        if before_st == after_st:
            continue
        event_date = str(row.get("变更日期") or "")[:10]
        events.append({
            "code": code, "date": event_date, "event_type": "st_status_change",
            "state": "st_start" if after_st else "st_end",
            "before_name": before, "after_name": after,
            "source": "szse_public_name_change_via_akshare",
            "confidence": "high", "known_at": event_date,
        })
    events.sort(key=lambda item: (item["code"], item["date"]))
    payload = {
        "status": "partial", "updated_at": now_str(), "exchange": "SZ",
        "source": "szse_public_name_change", "rows_scanned": int(len(frame)),
        "event_count": len(events), "events": events,
        "limitations": ["上海主板尚无等价批量日期表", "名称变更日视为新状态生效日"],
    }
    _write(output_path, payload)
    return payload


if __name__ == "__main__":
    run_st_event_job()
