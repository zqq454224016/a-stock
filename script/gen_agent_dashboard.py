#!/usr/bin/env python3
"""生成 Agent 统一看板与个股解释页（P4-1）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "assets" / "data" / "agent"
DATA_DIR = ROOT / "assets" / "data"
REPORTS_DIR = ROOT / "reports" / "agent"


def load_reports() -> list[dict]:
    index_path = AGENT_DIR / "index.json"
    reports: list[dict] = []
    if index_path.exists():
        for row in json.loads(index_path.read_text(encoding="utf-8")).get("reports", []):
            path = AGENT_DIR / f"{row['code']}.json"
            if path.exists():
                reports.append(json.loads(path.read_text(encoding="utf-8")))
        return reports
    for path in AGENT_DIR.glob("*.json"):
        if path.stem == "index":
            continue
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    return reports


def _strategy_label(name: str) -> str:
    sys.path.insert(0, str(ROOT))
    from quant_system.utils.i18n_labels import STRATEGY_LABELS, translate_label
    return translate_label(name, STRATEGY_LABELS)


def _verdict_badge(v: str) -> str:
    sys.path.insert(0, str(ROOT))
    from quant_system.utils.i18n_labels import translate_direction, translate_status, translate_verdict

    colors = {
        "positive": "#10b981", "negative": "#ef4444", "neutral": "#6b7280",
        "ok": "#10b981", "weak": "#ef4444", "mixed": "#f59e0b",
        "aligned": "#10b981", "divergent": "#ef4444", "partial": "#f59e0b",
        "up": "#10b981", "down": "#ef4444",
        "pass": "#10b981", "warn": "#f59e0b", "fail": "#ef4444",
    }
    label = translate_verdict(v)
    if label == v:
        label = translate_direction(v)
    if label == v:
        label = translate_status(v)
    c = colors.get(v, "#6b7280")
    return f'<span style="color:{c};font-weight:600">{label}</span>'


def render_stock_page(data: dict) -> str:
    code = data["code"]
    sel = data.get("stock_selection") or {}
    diag = data.get("strategy_diagnosis") or {}
    rev = data.get("prediction_review") or {}
    health = data.get("data_health") or {}

    def li(items):
        return "".join(f"<li>{x}</li>" for x in items) or "<li>—</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{data.get('name')} Agent 报告 · {code}</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        <a href="index.html">Agent 看板</a> / {code}
      </nav>
      <h1 class="site-title">{data.get('name')} <span class="stock-code">{code}</span></h1>
      <p class="site-subtitle">{data.get('summary')} · 置信度 {data.get('confidence')} · {data.get('updated_at')}</p>
      <p style="color:var(--color-muted);font-size:0.85rem">{data.get('disclaimer')}</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="stats-row">
      <div class="stat-card"><div class="name">选股结论</div><div class="value">{_verdict_badge(sel.get('verdict',''))}</div><div class="change">综合分 {sel.get('composite_score','—')}</div></div>
      <div class="stat-card"><div class="name">策略诊断</div><div class="value">{_verdict_badge(diag.get('verdict',''))}</div><div class="change">{_strategy_label(diag.get('strategy',''))}</div></div>
      <div class="stat-card"><div class="name">预测复盘</div><div class="value">{_verdict_badge(rev.get('alignment',''))}</div><div class="change">{rev.get('horizon','—')} {_verdict_badge(rev.get('direction',''))}</div></div>
      <div class="stat-card"><div class="name">数据质量</div><div class="value">{health.get('quality_score','—')}</div><div class="change">{_verdict_badge(health.get('status',''))}</div></div>
    </section>

    <section class="panel"><h2>选股解释</h2><p>{sel.get('headline','')}</p>
      <p><strong>证据</strong></p><ul>{li(sel.get('evidence') or [])}</ul>
      <p><strong>驱动</strong></p><ul>{li(sel.get('drivers') or [])}</ul>
      <p><strong>风险</strong></p><ul>{li(sel.get('risks') or [])}</ul>
    </section>

    <section class="panel"><h2>策略诊断</h2><ul>{li(diag.get('findings') or [])}</ul>
      <p><strong>建议</strong></p><ul>{li(diag.get('suggestions') or [])}</ul>
    </section>

    <section class="panel"><h2>预测复盘</h2><ul>{li(rev.get('notes') or [])}</ul>
      <p><strong>失效条件</strong></p><ul>{li(rev.get('failure_conditions') or [])}</ul>
    </section>

    <section class="panel"><h2>关联报表</h2>
      <p>
        <a href="../stock/{code}.html">个股分析</a> ·
        <a href="../backtest/{code}_ma_cross.html">回测 MA</a> ·
        <a href="../backtest/{code}_multi_factor.html">回测多因子</a> ·
        <a href="../predict/index.html">预测汇总</a> ·
        <a href="../factors/index.html">因子排名</a>
      </p>
    </section>
  </main>
</body>
</html>"""


def render_dashboard(reports: list[dict], market: dict) -> str:
    cards = []
    for r in reports:
        code = r["code"]
        sel = r.get("stock_selection") or {}
        diag = r.get("strategy_diagnosis") or {}
        rev = r.get("prediction_review") or {}
        cards.append(f"""
        <article class="panel" style="margin-bottom:1rem">
          <h3><a href="{code}.html">{r.get('name')} ({code})</a></h3>
          <p>{r.get('summary')}</p>
          <p>选股 { _verdict_badge(sel.get('verdict','')) } ·
             策略 { _verdict_badge(diag.get('verdict','')) } ·
             预测 { _verdict_badge(rev.get('alignment','')) }</p>
          <p style="font-size:0.9rem">
            <a href="../stock/{code}.html">个股</a> ·
            <a href="../backtest/{code}_ma_cross.html">回测</a> ·
            <a href="{code}.html">完整 Agent 报告</a>
          </p>
        </article>""")

    indices = market.get("indices") or []
    idx_line = " · ".join(
        f"{i.get('name')} {i.get('change_pct')}%"
        for i in indices[:4]
    ) or "—"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>Agent 统一看板 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        Agent 看板
      </nav>
      <h1 class="site-title">Agent 统一看板 <span class="stock-code">P4-1</span></h1>
      <p class="site-subtitle">
        交易日 {market.get('trade_date', '—')} · 大盘 {idx_line}
      </p>
      <p style="color:var(--color-muted);font-size:0.85rem">规则型解释 · 不自动下单 · 证据来自本地 JSON</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="stats-row">
      <div class="stat-card"><div class="name">自选股</div><div class="value">{len(reports)}</div></div>
      <div class="stat-card"><div class="name">行情入口</div><div class="value" style="font-size:1rem"><a href="../live/index.html">盘中看板</a></div></div>
      <div class="stat-card"><div class="name">因子排名</div><div class="value" style="font-size:1rem"><a href="../factors/index.html">因子</a></div></div>
      <div class="stat-card"><div class="name">预测汇总</div><div class="value" style="font-size:1rem"><a href="../predict/index.html">预测</a></div></div>
    </section>
    {''.join(cards) or '<p>运行 ./run.sh agent</p>'}
  </main>
</body>
</html>"""


def main() -> None:
    reports = load_reports()
    market = {}
    latest = DATA_DIR / "latest.json"
    if latest.exists():
        market = json.loads(latest.read_text(encoding="utf-8"))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "index.html").write_text(render_dashboard(reports, market), encoding="utf-8")
    for r in reports:
        (REPORTS_DIR / f"{r['code']}.html").write_text(render_stock_page(r), encoding="utf-8")
    print(f"[gen_agent_dashboard] 已生成 {REPORTS_DIR}/index.html ({len(reports)} 只)")

    from script.report_index_utils import sync_report_index_hubs
    sync_report_index_hubs()


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    main()
