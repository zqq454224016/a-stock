"""构建数据产物注册表。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from quant_system.monitoring.snapshot import MODULE_SPECS
from quant_system.storage.json_store import JsonStore
from quant_system.utils.time_utils import now_str

DATA_REGISTRY_VERSION = "1.0.0"

EXPECTED_COMMANDS = {
    "market": "market",
    "stocks": "stock",
    "enhance": "enhance",
    "factors": "factor",
    "backtest": "backtest",
    "predictions": "predict",
    "selector": "selector",
    "decisions": "decision",
    "review": "review",
    "replay": "replay",
    "impact": "impact",
    "attribution": "attribution",
    "agent": "agent",
    "trading": "simtrade",
    "portfolio": "portfolio",
    "recommendations": "recommend",
    "framework": "framework",
    "console": "console",
    "quality": "inspect",
    "task_runs": "任意 CLI 命令",
}


def _resolve_path(store: JsonStore, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    return (store.config.json_data_dir / path).resolve()


def _read_json(store: JsonStore, path: Path) -> dict[str, Any]:
    if path.exists() and path.suffix == ".json":
        try:
            payload = store.read(path)
            return payload if isinstance(payload, dict) else {"rows": payload}
        except Exception:
            return {}
    return {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:10], fmt)
        except ValueError:
            continue
    return None


def _item_count(payload: dict[str, Any]) -> int:
    for key in ("stocks", "items", "decisions", "predictions", "reports", "results", "positions", "rows", "runs"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    if payload.get("periods"):
        return sum(len((period.get("evaluated") or [])) for period in payload["periods"].values())
    if payload.get("universe"):
        return len(payload.get("universe") or [])
    return 1 if payload else 0


def _field_summary(payload: dict[str, Any]) -> dict[str, Any]:
    fields = sorted(str(key) for key in payload.keys())[:40]
    list_fields = {
        str(key): len(value)
        for key, value in payload.items()
        if isinstance(value, list)
    }
    dict_fields = sorted(str(key) for key, value in payload.items() if isinstance(value, dict))[:30]
    return {
        "top_level_fields": fields,
        "list_fields": list_fields,
        "dict_fields": dict_fields,
    }


def _data_quality(payload: dict[str, Any], exists: bool) -> dict[str, Any]:
    limitations = list(payload.get("limitations") or [])
    degraded = bool(payload.get("degraded")) or "degraded" in limitations
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    return {
        "exists": exists,
        "degraded": degraded,
        "quality_status": quality.get("status", ""),
        "quality_score": quality.get("quality_score"),
        "limitations": limitations,
    }


def _task_runs(store: JsonStore) -> list[dict[str, Any]]:
    path = store.task_runs_dir() / "index.json"
    payload = _read_json(store, path)
    return list(payload.get("runs") or [])


def _artifact_matches(store: JsonStore, artifact_path: str, spec_path: str) -> bool:
    return _resolve_path(store, artifact_path) == _resolve_path(store, spec_path)


def _latest_task_for_path(store: JsonStore, spec_path: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    for run in runs:
        for artifact in run.get("artifacts") or []:
            if _artifact_matches(store, str(artifact.get("path") or ""), spec_path):
                return {
                    "run_id": run.get("run_id"),
                    "command": run.get("command"),
                    "status": run.get("status"),
                    "ended_at": run.get("ended_at"),
                    "duration_sec": run.get("duration_sec"),
                    "artifact_exists_at_finish": artifact.get("exists"),
                }
    return {}


def _artifact_record(store: JsonStore, spec: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    rel = spec["path"]
    path = _resolve_path(store, rel)
    exists = path.exists()
    payload = _read_json(store, path)
    stat = path.stat() if exists else None
    updated_at = payload.get("updated_at") if payload else ""
    if not updated_at and stat:
        updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    latest_task = _latest_task_for_path(store, rel, runs)
    return {
        "registry_version": DATA_REGISTRY_VERSION,
        "module": spec["name"],
        "label": spec["label"],
        "path": rel,
        "absolute_path": str(path),
        "exists": exists,
        "size": stat.st_size if stat else None,
        "file_mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S") if stat else "",
        "updated_at": updated_at,
        "record_count": _item_count(payload),
        "field_summary": _field_summary(payload),
        "data_quality": _data_quality(payload, exists),
        "dependencies": spec.get("deps") or [],
        "generated_by": latest_task,
        "source": {
            "declared_output": rel,
            "expected_command": EXPECTED_COMMANDS.get(spec["name"], spec["name"]),
            "payload_trade_date": payload.get("trade_date", ""),
            "payload_version": payload.get("version") or payload.get("data_version") or payload.get("monitoring_version") or payload.get("daily_attribution_version") or "",
        },
        "registered_at": now_str(),
    }


def _dynamic_lineage(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_map = {item["module"]: "ok" if item.get("exists") else "missing" for item in items}
    return [
        {
            "module": item["module"],
            "label": item["label"],
            "inputs": item.get("dependencies") or [],
            "output": item.get("path"),
            "generated_by": (item.get("generated_by") or {}).get("command", ""),
            "input_status": {dep: status_map.get(dep, "unknown") for dep in item.get("dependencies") or []},
        }
        for item in items
    ]


def build_data_registry(store: JsonStore | None = None) -> dict[str, Any]:
    store = store or JsonStore()
    runs = _task_runs(store)
    specs = [spec for spec in MODULE_SPECS if spec["name"] != "data_registry"]
    items = [_artifact_record(store, spec, runs) for spec in specs]
    summary = {
        "artifact_count": len(items),
        "existing_count": sum(1 for item in items if item.get("exists")),
        "missing_count": sum(1 for item in items if not item.get("exists")),
        "degraded_count": sum(1 for item in items if (item.get("data_quality") or {}).get("degraded")),
        "with_task_lineage_count": sum(1 for item in items if item.get("generated_by")),
    }
    return {
        "registry_version": DATA_REGISTRY_VERSION,
        "updated_at": now_str(),
        "summary": summary,
        "items": items,
        "lineage": _dynamic_lineage(items),
        "limitations": [
            "首版注册表从关键产物、静态依赖和最近任务日志推导血缘。",
            "未被 CLI 任务日志命中的旧产物只能记录文件时间和字段摘要。",
            "缓存命中、降级原因和字段质量仍需要后续各任务写入更细粒度元数据。",
        ],
    }
