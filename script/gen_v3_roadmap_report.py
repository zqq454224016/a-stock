#!/usr/bin/env python3
"""生成 v3 稳定化路线报告。"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "planning" / "v3_roadmap.json"
REPORTS_DIR = ROOT / "reports" / "planning"


def _read() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}


def _li(items: list[str]) -> str:
    return "".join(f"<li>{html.escape(str(x))}</li>" for x in items) or "<li>—</li>"


def _phase_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{item.get('id')}</td><td>{html.escape(str(item.get('title')))}</td>"
            f"<td>{item.get('priority')}</td><td>{html.escape(str(item.get('status')))}</td>"
            f"<td>{html.escape(str(item.get('goal')))}</td><td>{'；'.join(item.get('outputs') or [])}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="6">暂无路线</td></tr>'


def render(payload: dict) -> str:
    current = payload.get("current_next") or {}
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>v3 稳定化路线 · A股全景</title>
<link rel="stylesheet" href="../../css/common.css"><link rel="stylesheet" href="../../css/report.css"></head>
<body><header class="site-header"><div class="container"><nav class="breadcrumb"><a href="../../index.html">首页</a> / <a href="../index.html">报表列表</a> / v3 路线</nav>
<h1 class="site-title">v3 稳定化与扩展路线</h1><p class="site-subtitle">{html.escape(str(payload.get('objective', '')))}</p></div></header>
<main class="container report-body">
  <section class="stats-row">
    <div class="stat-card"><div class="name">路线版本</div><div class="value">{payload.get('roadmap_version', '—')}</div></div>
    <div class="stat-card"><div class="name">阶段数量</div><div class="value">{len(payload.get('phases') or [])}</div></div>
    <div class="stat-card"><div class="name">当前唯一下一步</div><div class="value" style="font-size:1rem">{current.get('id', '—')}</div><div class="change">{html.escape(str(current.get('title', '—')))}</div></div>
    <div class="stat-card"><div class="name">更新时间</div><div class="value" style="font-size:1rem">{payload.get('updated_at', '—')}</div></div>
  </section>
  <section class="table-section"><h2>执行顺序</h2><table class="data-table"><thead><tr><th>编号</th><th>任务</th><th>优先级</th><th>状态</th><th>目标</th><th>产物</th></tr></thead><tbody>{_phase_rows(payload.get('phases') or [])}</tbody></table></section>
  <section class="table-section"><h2>当前任务验收</h2><ul>{_li(current.get('acceptance') or [])}</ul></section>
  <section class="table-section"><h2>v2 已完成基础</h2><ul>{_li(payload.get('completed_v2') or [])}</ul></section>
  <section class="table-section"><h2>原则</h2><ul>{_li(payload.get('principles') or [])}</ul></section>
  <section class="table-section"><h2>开放风险</h2><ul>{_li(payload.get('open_risks') or [])}</ul></section>
</main></body></html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "v3.html"
    out.write_text(render(_read()), encoding="utf-8")
    print(f"[gen_v3_roadmap_report] 已生成 {out}")


if __name__ == "__main__":
    main()
