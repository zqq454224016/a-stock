"""JSON compatibility repository for the normalized instrument universe."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from quant_system.utils.time_utils import now_str


class JsonUniverseRepository:
    def __init__(self, path: Path):
        self.path = path

    def save(self, rows: list[dict[str, Any]], *, source: str) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset": "market.instruments",
            "schema_version": "1.0.0",
            "source": source,
            "updated_at": now_str(),
            "count": len(rows),
            "stocks": rows,
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        self.path.write_text(content, encoding="utf-8")
        snapshot = self.path.parent / "snapshots" / f"{date.today().isoformat()}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(content, encoding="utf-8")
        manifest = self.path.parent / "manifest.json"
        manifest.write_text(json.dumps({
            "dataset": "market.instruments",
            "schema_version": "1.0.0",
            "source": source,
            "latest_snapshot": snapshot.name,
            "updated_at": payload["updated_at"],
            "count": len(rows),
            "primary_key": ["symbol", "effective_from"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("stocks") or []
            return rows if isinstance(rows, list) else []
        except (OSError, json.JSONDecodeError, TypeError):
            return []
