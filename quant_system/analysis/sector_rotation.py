"""Deterministic sector rotation evidence built from local industry history.

This module is deliberately score-neutral: it creates auditable context for
research and does not alter stock scores or recommendations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.utils.time_utils import now_str


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _return(rows: list[dict[str, Any]], days: int) -> float | None:
    if len(rows) <= days:
        return None
    latest = _number(rows[-1].get("close"))
    base = _number(rows[-days - 1].get("close"))
    if latest is None or base in (None, 0):
        return None
    return round((latest / base - 1) * 100, 4)


def _breadth(rows: list[dict[str, Any]], days: int = 20) -> float | None:
    changes = [_number(row.get("change_pct")) for row in rows[-days:]]
    changes = [value for value in changes if value is not None]
    if not changes:
        return None
    return round(sum(value > 0 for value in changes) / len(changes) * 100, 2)


def _constituent_breadth(
    root: Path,
    industry: str,
    trade_date: str,
    cache: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Measure constituent diffusion without using future bars."""
    membership_path = root / "sector_data" / "membership" / f"{industry.replace('/', '_')}.json"
    try:
        members = json.loads(membership_path.read_text(encoding="utf-8")).get("members") or []
    except (OSError, ValueError, TypeError):
        return {"constituent_count": 0, "breadth_1d_pct": None, "breadth_5d_pct": None, "breadth_20d_pct": None}
    one, five, twenty = [], [], []
    for member in members:
        code = str(member.get("code") or "").zfill(6)
        if code not in cache:
            path = root / "stocks" / f"{code}.json"
            try:
                cache[code] = json.loads(path.read_text(encoding="utf-8")).get("kline") or []
            except (OSError, ValueError, TypeError):
                cache[code] = []
        rows = [row for row in cache[code] if str(row.get("date") or "")[:10] <= str(trade_date)[:10]]
        if len(rows) < 2:
            continue
        latest = _number(rows[-1].get("close"))
        for target, bucket in ((1, one), (5, five), (20, twenty)):
            if len(rows) <= target:
                continue
            base = _number(rows[-target - 1].get("close"))
            if latest is not None and base not in (None, 0):
                bucket.append(latest / base - 1)
    pct = lambda values: round(sum(value > 0 for value in values) / len(values) * 100, 2) if values else None
    return {
        "constituent_count": len(one),
        "breadth_1d_pct": pct(one),
        "breadth_5d_pct": pct(five),
        "breadth_20d_pct": pct(twenty),
    }


def build_sector_rotation(data_dir: Path | None = None) -> dict[str, Any]:
    root = data_dir or DBConfig().json_data_dir
    history_dir = root / "sector_data" / "history"
    items: list[dict[str, Any]] = []
    constituent_cache: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(history_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
        if len(rows) < 21:
            continue
        latest = rows[-1]
        amount = _number(latest.get("amount")) or 0.0
        item = {
            "industry": payload.get("industry") or path.stem,
            "trade_date": latest.get("date"),
            "return_3d_pct": _return(rows, 3),
            "return_5d_pct": _return(rows, 5),
            "return_20d_pct": _return(rows, 20),
            "latest_amount": round(amount, 4),
            # Index-history breadth is retained for diagnostics; constituent
            # breadth is the preferred diffusion measure when membership and
            # stock K-lines are available.
            "index_breadth_20d_pct": _breadth(rows),
            "history_rows": len(rows),
        }
        item.update(_constituent_breadth(root, str(item["industry"]), str(item["trade_date"]), constituent_cache))
        items.append(item)
    # 混入停更的旧板块文件时，只用最新交易日那一批，避免 trade_date 被旧缓存拖住。
    latest_date = max((str(item.get("trade_date") or "") for item in items), default="")
    if latest_date:
        items = [item for item in items if str(item.get("trade_date") or "") == latest_date]
    total_amount = sum(item["latest_amount"] for item in items)
    for item in items:
        item["amount_share_pct"] = round(item["latest_amount"] / total_amount * 100, 4) if total_amount else None
        values = [item.get(key) for key in ("return_3d_pct", "return_5d_pct", "return_20d_pct")]
        valid = [value for value in values if value is not None]
        item["rotation_score"] = round(
            (valid[0] * 0.45 + valid[1] * 0.35 + valid[2] * 0.20) if len(valid) == 3 else 0.0,
            4,
        )
    items.sort(key=lambda item: item.get("rotation_score") or -999, reverse=True)
    payload = {
        "version": "1.0.0",
        "updated_at": now_str(),
        "trade_date": max((str(item.get("trade_date") or "") for item in items), default=""),
        "method": "close_return_3_5_20d_plus_latest_amount_share_and_history_breadth",
        "score_policy": "context_only_not_used_in_stock_score",
        "count": len(items),
        "leaders": items[:10],
        "laggards": list(reversed(items[-10:])),
        "items": items,
    }
    path = root / "sector_data" / "rotation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build_sector_rotation()
    print(json.dumps({"trade_date": result["trade_date"], "count": result["count"]}, ensure_ascii=False))
