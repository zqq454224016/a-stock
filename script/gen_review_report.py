#!/usr/bin/env python3
"""生成后验复盘报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "review"
REPORTS_DIR = ROOT / "reports" / "review"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_payloads() -> list[dict]:
    index = _read(DATA_DIR / "index.json")
    rows = index.get("items") or []
    payloads = []
    if rows:
        for row in rows:
            path = DATA_DIR / f"{row.get('code')}.json"
            if path.exists():
                payloads.append(_read(path))
    else:
        for path in sorted(DATA_DIR.glob("*.json")):
            if path.stem != "index":
                payloads.append(_read(path))
    return payloads


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _ret(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}%"


def _hit(value) -> str:
    if value is True:
        return "命中"
    if value is False:
        return "未命中"
    return "—"


def _list(items: list[str]) -> str:
    return "<br>".join(items or ["—"])


def render_index(payloads: list[dict]) -> str:
    rows = []
    for p in payloads:
        s = p.get("summary") or {}
        rows.append(f"""
        <tr>
          <td><a href="{p.get('code')}.html">{p.get('code')}</a></td>
          <td>{p.get('name') or ''}</td>
          <td>{p.get('trade_date') or '—'}</td>
          <td>{s.get('evaluated_count') or 0}</td>
          <td>{s.get('pending_count') or 0}</td>
          <td>{_pct(s.get('hit_rate'))}</td>
          <td>{_ret(s.get('avg_return_pct'))}</td>
          <td>{_ret(s.get('worst_adverse_pct'))}</td>
          <td>{_list((s.get('failure_reasons') or [])[:2])}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="9">运行 python quant_system/main.py review</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>后验复盘 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">后验复盘</h1>
      <p class="site-subtitle">统计 prediction、selector、decision 后 1/5/20 日收益、命中率和最大不利波动</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>信号日</th><th>已评估</th><th>待评估</th><th>命中率</th><th>平均收益</th><th>最大不利</th><th>失效原因</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def _section_rows(title: str, section: dict) -> str:
    rows = []
    for item in section.get("items") or []:
        rows.append(f"""
        <tr>
          <td>{title}</td>
          <td>{item.get('horizon')}</td>
          <td>{item.get('status')}</td>
          <td>{item.get('target_date') or '—'}</td>
          <td>{_ret(item.get('return_pct'))}</td>
          <td>{_ret(item.get('max_favorable_pct'))}</td>
          <td>{_ret(item.get('max_adverse_pct'))}</td>
          <td>{_hit(item.get('hit'))}</td>
          <td>{_list(item.get('failure_reasons') or [])}</td>
        </tr>""")
    return "".join(rows)


def render_detail(p: dict) -> str:
    sections = p.get("sections") or {}
    rows = (
        _section_rows("预测", sections.get("prediction") or {})
        + _section_rows("候选", sections.get("selector") or {})
        + _section_rows("决策", sections.get("decision") or {})
    ) or '<tr><td colspan="9">暂无复盘项目</td></tr>'
    s = p.get("summary") or {}
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{p.get('code')} 后验复盘 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">{p.get('name')} ({p.get('code')})</h1>
      <p class="site-subtitle">信号日 {p.get('trade_date')} · 命中率 {_pct(s.get('hit_rate'))}</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="summary-grid">
      <div class="summary-card"><span>已评估</span><strong>{s.get('evaluated_count') or 0}</strong></div>
      <div class="summary-card"><span>待评估</span><strong>{s.get('pending_count') or 0}</strong></div>
      <div class="summary-card"><span>平均收益</span><strong>{_ret(s.get('avg_return_pct'))}</strong></div>
      <div class="summary-card"><span>最大不利</span><strong>{_ret(s.get('worst_adverse_pct'))}</strong></div>
    </section>
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>类型</th><th>周期</th><th>状态</th><th>目标日</th><th>收益</th><th>最大有利</th><th>最大不利</th><th>命中</th><th>失效原因</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">后验复盘用于校准系统，不构成投资建议；待评估表示信号日之后 K 线不足。</p>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payloads = load_payloads()
    (REPORTS_DIR / "index.html").write_text(render_index(payloads), encoding="utf-8")
    for payload in payloads:
        code = payload.get("code")
        if code:
            (REPORTS_DIR / f"{code}.html").write_text(render_detail(payload), encoding="utf-8")
    print(f"[gen_review_report] 已生成 {REPORTS_DIR} ({len(payloads)} 只)")


if __name__ == "__main__":
    main()
