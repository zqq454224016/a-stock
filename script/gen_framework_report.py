#!/usr/bin/env python3
"""生成模块化算法框架报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "framework" / "snapshot.json"
REPORTS_DIR = ROOT / "reports" / "framework"


def _read() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}


def _module_rows(coverage: dict) -> str:
    rows = []
    for name, item in (coverage.get("module_coverage") or {}).items():
        rows.append(f"<tr><td>{name}</td><td>{item.get('count', 0)}</td><td>{item.get('ratio', 0) * 100:.0f}%</td></tr>")
    return "".join(rows) or '<tr><td colspan="3">暂无覆盖数据</td></tr>'


def _risk_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{item.get('code')}</td><td>{item.get('level')}</td><td>{'是' if item.get('passed') else '否'}</td>"
            f"<td>{'；'.join(item.get('blockers') or ['—'])}</td><td>{'；'.join(item.get('warnings') or ['—'])}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="5">暂无风险检查</td></tr>'


def _intent_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{item.get('code')}</td><td>{item.get('action')}</td><td>{item.get('target_position_pct')}</td>"
            f"<td>{'是' if item.get('allowed') else '否'}</td><td>{'是' if item.get('requires_human_review') else '否'}</td>"
            f"<td>{item.get('reason')}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="6">暂无执行意图</td></tr>'


def _signal_rows(items: list[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<tr><td>{item.get('code')}</td><td>{item.get('source')}</td><td>{item.get('direction')}</td>"
            f"<td>{item.get('strength')}</td><td>{item.get('confidence')}</td><td>{item.get('horizon')}</td>"
            f"<td>{'；'.join(item.get('evidence') or ['—'])}</td><td>{'；'.join(item.get('risks') or ['—'])}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="8">暂无标准信号</td></tr>'


def render(payload: dict) -> str:
    coverage = payload.get("coverage") or {}
    limitations = "".join(f"<li>{x}</li>" for x in payload.get("limitations") or [])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>模块化算法框架 · A股全景</title>
<link rel="stylesheet" href="../../css/common.css"><link rel="stylesheet" href="../../css/report.css"></head>
<body><header class="site-header"><div class="container"><h1 class="site-title">模块化算法框架</h1>
<p class="site-subtitle">统一 Universe、Signal、Target、Risk、Execution、Analyzer 契约</p></div></header>
<main class="container report-body">
  <section class="summary-grid">
    <div class="summary-card"><span>框架版本</span><strong>{payload.get('framework_version', '—')}</strong></div>
    <div class="summary-card"><span>股票数量</span><strong>{coverage.get('universe_count', 0)}</strong></div>
    <div class="summary-card"><span>标准信号</span><strong>{coverage.get('signal_count', 0)}</strong></div>
    <div class="summary-card"><span>更新时间</span><strong>{payload.get('updated_at', '—')}</strong></div>
  </section>
  <section class="table-section"><h2>模块覆盖</h2><table class="data-table"><thead><tr><th>模块</th><th>数量</th><th>覆盖率</th></tr></thead><tbody>{_module_rows(coverage)}</tbody></table></section>
  <section class="table-section"><h2>标准信号</h2><table class="data-table"><thead><tr><th>代码</th><th>来源</th><th>方向</th><th>强度</th><th>置信度</th><th>周期</th><th>证据</th><th>风险</th></tr></thead><tbody>{_signal_rows(payload.get('signals') or [])}</tbody></table></section>
  <section class="table-section"><h2>风险门禁</h2><table class="data-table"><thead><tr><th>代码</th><th>等级</th><th>通过</th><th>阻断项</th><th>提示项</th></tr></thead><tbody>{_risk_rows(payload.get('risk_checks') or [])}</tbody></table></section>
  <section class="table-section"><h2>执行意图</h2><table class="data-table"><thead><tr><th>代码</th><th>动作</th><th>目标仓位</th><th>允许进入确认</th><th>人工确认</th><th>原因</th></tr></thead><tbody>{_intent_rows(payload.get('execution_intents') or [])}</tbody></table></section>
  <section class="table-section"><h2>使用边界</h2><ul>{limitations}</ul></section>
</main></body></html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(_read()), encoding="utf-8")
    print(f"[gen_framework_report] 已生成 {out}")


if __name__ == "__main__":
    main()
