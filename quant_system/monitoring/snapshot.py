"""构建本地监控快照。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from quant_system.config.schedule_config import ScheduleConfig
from quant_system.storage.json_store import JsonStore
from quant_system.utils.time_utils import now_str

MONITORING_VERSION = "1.0.0"

MODULE_SPECS = [
    {"name": "market", "label": "大盘行情", "path": "latest.json", "max_age_hours": 96, "deps": []},
    {"name": "stocks", "label": "个股分析", "path": "stocks/index.json", "max_age_hours": 96, "deps": ["market"]},
    {"name": "enhance", "label": "数据增强", "path": "enhance/index.json", "max_age_hours": 240, "deps": ["stocks", "market"]},
    {"name": "factors", "label": "因子", "path": "factors/index.json", "max_age_hours": 120, "deps": ["stocks"]},
    {"name": "backtest", "label": "策略回测", "path": "backtest/index.json", "max_age_hours": 240, "deps": ["stocks", "factors"]},
    {"name": "predictions", "label": "走势预测", "path": "predictions/index.json", "max_age_hours": 120, "deps": ["stocks", "factors", "backtest"]},
    {"name": "selector", "label": "上涨候选", "path": "selector/index.json", "max_age_hours": 120, "deps": ["predictions", "factors", "impact"]},
    {"name": "decisions", "label": "操作建议", "path": "decisions/index.json", "max_age_hours": 120, "deps": ["predictions", "selector", "agent", "impact"]},
    {"name": "review", "label": "后验复盘", "path": "review/index.json", "max_age_hours": 240, "deps": ["predictions", "selector", "decisions"]},
    {"name": "replay", "label": "十日推演", "path": "replay/index.json", "max_age_hours": 240, "deps": ["stocks", "impact"]},
    {"name": "impact", "label": "实际影响", "path": "impact/index.json", "max_age_hours": 240, "deps": ["enhance", "review"]},
    {"name": "attribution", "label": "每日归因", "path": "attribution/index.json", "max_age_hours": 120, "deps": ["stocks", "market", "impact", "replay"]},
    {"name": "agent", "label": "Agent", "path": "agent/index.json", "max_age_hours": 120, "deps": ["stocks", "predictions", "factors"]},
    {"name": "trading", "label": "模拟交易", "path": "trading/index.json", "max_age_hours": 240, "deps": ["decisions", "predictions"]},
    {"name": "portfolio", "label": "组合管理", "path": "portfolio/summary.json", "max_age_hours": 240, "deps": ["decisions", "trading"]},
    {"name": "recommendations", "label": "多周期推荐", "path": "recommendations/summary.json", "max_age_hours": 240, "deps": ["market", "selector", "predictions", "impact", "replay"]},
    {"name": "framework", "label": "模块框架", "path": "framework/snapshot.json", "max_age_hours": 240, "deps": ["stocks", "predictions", "selector", "decisions"]},
    {"name": "console", "label": "统一控制台", "path": "../../reports/console/index.html", "max_age_hours": 240, "deps": ["stocks", "selector", "decisions", "agent", "framework"]},
    {"name": "quality", "label": "质量巡检", "path": "quality/latest.json", "max_age_hours": 240, "deps": ["stocks"]},
    {"name": "task_runs", "label": "任务运行", "path": "task_runs/index.json", "max_age_hours": 240, "deps": []},
    {"name": "data_registry", "label": "数据注册表", "path": "data_registry/index.json", "max_age_hours": 120, "deps": ["task_runs"]},
]


def _read(store: JsonStore, rel: str) -> dict[str, Any]:
    path = _resolve_path(store, rel)
    if path.exists() and path.suffix == ".json":
        return store.read(path)
    return {}


def _resolve_path(store: JsonStore, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    return (store.config.json_data_dir / path).resolve()


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


def _age_hours(path: Path, payload: dict[str, Any], now: datetime) -> float | None:
    dt = _parse_dt(payload.get("updated_at")) if payload else None
    if dt is None and path.exists():
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 3600, 2)


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


def _module_status(spec: dict[str, Any], store: JsonStore, now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _resolve_path(store, spec["path"])
    payload = _read(store, spec["path"])
    exists = path.exists()
    age = _age_hours(path, payload, now)
    alerts: list[dict[str, Any]] = []
    status = "ok"
    if not exists:
        status = "missing"
        alerts.append(_alert("critical", spec["name"], f"{spec['label']}产物缺失", spec["path"]))
    elif age is not None and age > spec["max_age_hours"]:
        status = "stale"
        alerts.append(_alert("warning", spec["name"], f"{spec['label']}超过{spec['max_age_hours']}小时未更新", spec["path"]))
    return {
        "name": spec["name"],
        "label": spec["label"],
        "path": spec["path"],
        "exists": exists,
        "status": status,
        "age_hours": age,
        "item_count": _item_count(payload),
        "updated_at": payload.get("updated_at") if payload else "",
        "dependencies": spec["deps"],
    }, alerts


def _alert(level: str, module: str, message: str, source: str) -> dict[str, Any]:
    return {"level": level, "module": module, "message": message, "source": source}


def _quality_alerts(store: JsonStore) -> list[dict[str, Any]]:
    payload = _read(store, "quality/latest.json")
    alerts: list[dict[str, Any]] = []
    summary = payload.get("summary") or {}
    if summary.get("error", 0) > 0:
        alerts.append(_alert("critical", "quality", f"{summary['error']}只股票质量错误", "quality/latest.json"))
    if summary.get("warning", 0) > 0:
        alerts.append(_alert("warning", "quality", f"{summary['warning']}只股票质量警告", "quality/latest.json"))
    if summary.get("factor_blocked", 0) > 0:
        alerts.append(_alert("warning", "quality", f"{summary['factor_blocked']}只股票被阻断因子计算", "quality/latest.json"))
    return alerts


def _recommendation_alerts(store: JsonStore) -> list[dict[str, Any]]:
    payload = _read(store, "recommendations/summary.json")
    alerts: list[dict[str, Any]] = []
    for key, period in (payload.get("periods") or {}).items():
        if period.get("shortage_count", 0) > 0:
            alerts.append(_alert("info", "recommendations", f"{period.get('label', key)}推荐缺额{period['shortage_count']}只", "recommendations/summary.json"))
    return alerts


def _agent_alerts(store: JsonStore) -> list[dict[str, Any]]:
    payload = _read(store, "agent/index.json")
    alerts: list[dict[str, Any]] = []
    for row in payload.get("reports") or []:
        if row.get("policy_passed") is False:
            alerts.append(_alert("critical", "agent", f"{row.get('code')} Agent 权限校验未通过", "agent/index.json"))
        if row.get("provider") == "rule":
            # 当前允许降级，只做提示。
            alerts.append(_alert("info", "agent", f"{row.get('code')} 使用规则 Provider", "agent/index.json"))
    return alerts[:10]


def _framework_alerts(store: JsonStore) -> list[dict[str, Any]]:
    payload = _read(store, "framework/snapshot.json")
    coverage = payload.get("coverage") or {}
    alerts: list[dict[str, Any]] = []
    for name, item in (coverage.get("module_coverage") or {}).items():
        if item.get("ratio", 0) < 1:
            alerts.append(_alert("warning", "framework", f"{name} 覆盖率 {item.get('ratio', 0) * 100:.0f}%", "framework/snapshot.json"))
    return alerts


def _recent_task_runs(store: JsonStore, limit: int = 10) -> list[dict[str, Any]]:
    payload = _read(store, "task_runs/index.json")
    return list(payload.get("runs") or [])[:limit]


def _task_run_alerts(store: JsonStore) -> list[dict[str, Any]]:
    runs = _recent_task_runs(store, limit=10)
    alerts: list[dict[str, Any]] = []
    if not runs:
        return alerts
    latest = runs[0]
    if latest.get("status") == "failed":
        error = latest.get("error") or {}
        message = error.get("message") or "未记录异常信息"
        alerts.append(_alert("critical", "task_runs", f"最近任务 {latest.get('command')} 失败：{message}", latest.get("path", "task_runs/index.json")))
    failed_count = sum(1 for row in runs if row.get("status") == "failed")
    if failed_count > 1:
        alerts.append(_alert("warning", "task_runs", f"最近10次任务有{failed_count}次失败", "task_runs/index.json"))
    return alerts


def _registry_summary(store: JsonStore) -> dict[str, Any]:
    payload = _read(store, "data_registry/index.json")
    return payload.get("summary") or {}


def _lineage(module_status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_map = {item["name"]: item["status"] for item in module_status}
    return [
        {
            "module": spec["name"],
            "label": spec["label"],
            "inputs": spec["deps"],
            "output": spec["path"],
            "input_status": {dep: status_map.get(dep, "unknown") for dep in spec["deps"]},
        }
        for spec in MODULE_SPECS
    ]


def _schedule_status() -> list[dict[str, Any]]:
    cfg = ScheduleConfig()
    return [
        {"job": "daily_market", "cron": cfg.daily_market, "enabled": "daily_market" in cfg.enabled_jobs},
        {"job": "daily_stock", "cron": cfg.daily_stock, "enabled": "daily_stock" in cfg.enabled_jobs},
        {"job": "intraday_snapshot", "cron": cfg.intraday_snapshot, "enabled": "intraday_snapshot" in cfg.enabled_jobs},
        {"job": "data_inspect", "cron": cfg.data_inspect, "enabled": "data_inspect" in cfg.enabled_jobs},
        {"job": "backfill_weekly", "cron": cfg.backfill_weekly, "enabled": "backfill_weekly" in cfg.enabled_jobs},
    ]


def build_monitoring_snapshot(store: JsonStore | None = None) -> dict[str, Any]:
    store = store or JsonStore()
    now = datetime.now()
    modules: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    for spec in MODULE_SPECS:
        status, module_alerts = _module_status(spec, store, now)
        modules.append(status)
        alerts.extend(module_alerts)
    alerts.extend(_quality_alerts(store))
    alerts.extend(_recommendation_alerts(store))
    alerts.extend(_agent_alerts(store))
    alerts.extend(_framework_alerts(store))
    alerts.extend(_task_run_alerts(store))
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts = sorted(alerts, key=lambda item: severity_order.get(item["level"], 9))
    recent_task_runs = _recent_task_runs(store)
    latest_task = recent_task_runs[0] if recent_task_runs else {}
    latest_success = next((row for row in recent_task_runs if row.get("status") == "success"), {})
    registry_summary = _registry_summary(store)
    summary = {
        "module_count": len(modules),
        "ok_count": sum(1 for item in modules if item["status"] == "ok"),
        "missing_count": sum(1 for item in modules if item["status"] == "missing"),
        "stale_count": sum(1 for item in modules if item["status"] == "stale"),
        "critical_alerts": sum(1 for item in alerts if item["level"] == "critical"),
        "warning_alerts": sum(1 for item in alerts if item["level"] == "warning"),
        "info_alerts": sum(1 for item in alerts if item["level"] == "info"),
        "recent_task_count": len(recent_task_runs),
        "failed_task_runs": sum(1 for item in recent_task_runs if item.get("status") == "failed"),
        "last_task_command": latest_task.get("command", ""),
        "last_task_status": latest_task.get("status", ""),
        "last_success_at": latest_success.get("ended_at", ""),
        "registry_artifact_count": registry_summary.get("artifact_count", 0),
        "registry_with_task_lineage_count": registry_summary.get("with_task_lineage_count", 0),
        "registry_degraded_count": registry_summary.get("degraded_count", 0),
    }
    return {
        "monitoring_version": MONITORING_VERSION,
        "updated_at": now_str(),
        "summary": summary,
        "modules": modules,
        "alerts": alerts,
        "recent_task_runs": recent_task_runs,
        "data_registry": {
            "summary": registry_summary,
            "lineage": (_read(store, "data_registry/index.json").get("lineage") or [])[:20],
        },
        "lineage": _lineage(modules),
        "schedule": _schedule_status(),
        "limitations": [
            "当前为本地 JSON 与报告文件监控，尚未接入外部通知渠道。",
            "任务运行日志已覆盖 CLI 入口；长驻 scheduler 内部子任务仍需在后续版本补充独立 run_id。",
        ],
    }
