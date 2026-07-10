#!/usr/bin/env python3
"""生成监控告警与数据血缘报告。"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "monitoring" / "snapshot.json"
REPORTS_DIR = ROOT / "reports" / "monitoring"

LEVEL_LABEL = {"critical": "严重", "warning": "警告", "info": "提示"}
STATUS_LABEL = {"ok": "正常", "missing": "缺失", "stale": "过期"}
RUN_STATUS_LABEL = {"success": "成功", "failed": "失败", "skipped": "跳过"}


def _read() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}


def _alert_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{LEVEL_LABEL.get(item.get('level'), item.get('level'))}</td>"
            f"<td>{html.escape(str(item.get('module', '')))}</td>"
            f"<td>{html.escape(str(item.get('message', '')))}</td>"
            f"<td>{html.escape(str(item.get('source', '')))}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="4">暂无告警</td></tr>'


def _module_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{html.escape(str(item.get('label')))}</td>"
            f"<td>{STATUS_LABEL.get(item.get('status'), item.get('status'))}</td>"
            f"<td>{item.get('item_count')}</td><td>{item.get('age_hours') if item.get('age_hours') is not None else '—'}</td>"
            f"<td>{html.escape(str(item.get('path')))}</td><td>{'；'.join(item.get('dependencies') or []) or '—'}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="6">暂无模块状态</td></tr>'


def _lineage_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        inputs = "；".join(item.get("inputs") or []) or "源头"
        input_status = "；".join(f"{k}:{STATUS_LABEL.get(v, v)}" for k, v in (item.get("input_status") or {}).items()) or "—"
        rows.append(
            f"<tr><td>{html.escape(str(item.get('label')))}</td><td>{html.escape(inputs)}</td>"
            f"<td>{html.escape(str(item.get('output')))}</td><td>{html.escape(input_status)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="4">暂无血缘</td></tr>'


def _registry_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        inputs = "；".join(item.get("inputs") or []) or "源头"
        input_status = "；".join(f"{k}:{STATUS_LABEL.get(v, v)}" for k, v in (item.get("input_status") or {}).items()) or "—"
        rows.append(
            f"<tr><td>{html.escape(str(item.get('label')))}</td>"
            f"<td>{html.escape(str(item.get('generated_by') or '—'))}</td>"
            f"<td>{html.escape(inputs)}</td><td>{html.escape(str(item.get('output') or ''))}</td>"
            f"<td>{html.escape(input_status)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="5">暂无注册表血缘</td></tr>'


def _schedule_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{html.escape(str(item.get('job')))}</td><td>{html.escape(str(item.get('cron')))}</td>"
            f"<td>{'启用' if item.get('enabled') else '停用'}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="3">暂无调度配置</td></tr>'


def _task_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        error = item.get("error") or {}
        artifacts = "；".join(
            f"{x.get('path')}:{'存在' if x.get('exists') else '缺失'}"
            for x in (item.get("artifacts") or [])[:3]
        ) or "—"
        rows.append(
            f"<tr><td>{html.escape(str(item.get('command', '')))}</td>"
            f"<td>{RUN_STATUS_LABEL.get(item.get('status'), item.get('status'))}</td>"
            f"<td>{html.escape(str(item.get('started_at', '')))}</td>"
            f"<td>{html.escape(str(item.get('ended_at', '')))}</td>"
            f"<td>{item.get('duration_sec', '—')}</td>"
            f"<td>{html.escape(str(error.get('message') or item.get('skip_reason') or '—'))}</td>"
            f"<td>{html.escape(artifacts)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="7">暂无任务运行记录</td></tr>'


def render(payload: dict) -> str:
    summary = payload.get("summary") or {}
    registry = payload.get("data_registry") or {}
    registry_summary = registry.get("summary") or {}
    limitations = "".join(f"<li>{html.escape(str(x))}</li>" for x in payload.get("limitations") or [])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>监控告警与数据血缘 · A股全景</title>
<link rel="stylesheet" href="../../css/common.css"><link rel="stylesheet" href="../../css/report.css"></head>
<body><header class="site-header"><div class="container"><nav class="breadcrumb"><a href="../../index.html">首页</a> / <a href="../index.html">报表列表</a> / 监控告警</nav>
<h1 class="site-title">监控告警与数据血缘</h1><p class="site-subtitle">更新时间 {html.escape(str(payload.get('updated_at', '—')))}</p></div></header>
<main class="container report-body">
  <section class="stats-row">
    <div class="stat-card"><div class="name">模块数量</div><div class="value">{summary.get('module_count', 0)}</div></div>
    <div class="stat-card"><div class="name">正常模块</div><div class="value">{summary.get('ok_count', 0)}</div></div>
    <div class="stat-card"><div class="name">严重告警</div><div class="value">{summary.get('critical_alerts', 0)}</div></div>
    <div class="stat-card"><div class="name">警告</div><div class="value">{summary.get('warning_alerts', 0)}</div></div>
  </section>
  <section class="stats-row">
    <div class="stat-card"><div class="name">最近任务</div><div class="value">{summary.get('recent_task_count', 0)}</div></div>
    <div class="stat-card"><div class="name">失败任务</div><div class="value">{summary.get('failed_task_runs', 0)}</div></div>
    <div class="stat-card"><div class="name">上一任务</div><div class="value">{html.escape(str(summary.get('last_task_command') or '—'))}</div></div>
    <div class="stat-card"><div class="name">上一状态</div><div class="value">{RUN_STATUS_LABEL.get(summary.get('last_task_status'), summary.get('last_task_status') or '—')}</div></div>
  </section>
  <section class="stats-row">
    <div class="stat-card"><div class="name">注册产物</div><div class="value">{registry_summary.get('artifact_count', 0)}</div></div>
    <div class="stat-card"><div class="name">产物存在</div><div class="value">{registry_summary.get('existing_count', 0)}</div></div>
    <div class="stat-card"><div class="name">任务血缘</div><div class="value">{registry_summary.get('with_task_lineage_count', 0)}</div></div>
    <div class="stat-card"><div class="name">降级产物</div><div class="value">{registry_summary.get('degraded_count', 0)}</div></div>
  </section>
  <section class="table-section"><h2>告警</h2><table class="data-table"><thead><tr><th>级别</th><th>模块</th><th>内容</th><th>来源</th></tr></thead><tbody>{_alert_rows(payload.get('alerts') or [])}</tbody></table></section>
  <section class="table-section"><h2>最近任务</h2><table class="data-table"><thead><tr><th>命令</th><th>状态</th><th>开始</th><th>结束</th><th>耗时秒</th><th>原因</th><th>产物</th></tr></thead><tbody>{_task_rows(payload.get('recent_task_runs') or [])}</tbody></table></section>
  <section class="table-section"><h2>模块状态</h2><table class="data-table"><thead><tr><th>模块</th><th>状态</th><th>数量</th><th>距今小时</th><th>产物</th><th>依赖</th></tr></thead><tbody>{_module_rows(payload.get('modules') or [])}</tbody></table></section>
  <section class="table-section"><h2>注册表血缘</h2><table class="data-table"><thead><tr><th>模块</th><th>生成任务</th><th>输入</th><th>输出</th><th>输入状态</th></tr></thead><tbody>{_registry_rows((registry.get('lineage') or [])[:20])}</tbody></table></section>
  <section class="table-section"><h2>数据血缘</h2><table class="data-table"><thead><tr><th>模块</th><th>输入</th><th>输出</th><th>输入状态</th></tr></thead><tbody>{_lineage_rows(payload.get('lineage') or [])}</tbody></table></section>
  <section class="table-section"><h2>调度配置</h2><table class="data-table"><thead><tr><th>任务</th><th>Cron</th><th>状态</th></tr></thead><tbody>{_schedule_rows(payload.get('schedule') or [])}</tbody></table></section>
  <section class="table-section"><h2>使用边界</h2><ul>{limitations}</ul></section>
</main></body></html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(_read()), encoding="utf-8")
    print(f"[gen_monitoring_report] 已生成 {out}")


if __name__ == "__main__":
    main()
