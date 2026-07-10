#!/usr/bin/env python3
"""生成每日涨跌归因报告。"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "attribution"
REPORTS_DIR = ROOT / "reports" / "attribution"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_payloads() -> list[dict]:
    idx = _read(DATA_DIR / "index.json")
    rows = idx.get("items") or []
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


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _causes(items: list[dict]) -> str:
    if not items:
        return "—"
    lis = []
    for item in items[:4]:
        label = html.escape(str(item.get("label") or ""))
        evidence = html.escape(str(item.get("evidence") or ""))
        effect = {"bullish": "利多", "bearish": "利空", "neutral": "中性"}.get(item.get("effect"), item.get("effect") or "—")
        lis.append(f"<li><strong>{label}</strong> <span class=\"stock-code\">{effect}</span><br>{evidence}</li>")
    return "<ul>" + "".join(lis) + "</ul>"


def _item(payload: dict, idx: int) -> dict:
    items = payload.get("items") or []
    return items[idx] if len(items) > idx else {}


def render(payloads: list[dict]) -> str:
    rows = []
    for p in payloads:
        y = _item(p, 0)
        t = _item(p, 1)
        y_fact = y.get("fact") or {}
        t_fact = t.get("fact") or {}
        logic = p.get("logic_review") or {}
        next_watch = logic.get("next_watch") or {}
        rows.append(f"""
        <tr>
          <td><strong>{html.escape(str(p.get('name') or ''))}</strong><br><span class="stock-code">{html.escape(str(p.get('code') or ''))}</span></td>
          <td>{html.escape(str(p.get('previous_trade_date') or '—'))}<br>{_fmt_pct(y_fact.get('return_pct'))}</td>
          <td>{_causes(y.get('dominant_causes') or [])}</td>
          <td>{html.escape(str(p.get('trade_date') or '—'))}<br>{_fmt_pct(t_fact.get('return_pct'))}</td>
          <td>{_causes(t.get('dominant_causes') or [])}</td>
          <td>{'是' if logic.get('logic_broken') else '否'}<br>{html.escape('；'.join(logic.get('broken_reasons') or []) or '—')}</td>
          <td>修复 {next_watch.get('recover_price', '—')}<br>风险 {next_watch.get('risk_price', '—')}<br>压力 {next_watch.get('pressure_price', '—')}</td>
          <td>{html.escape('；'.join(p.get('limitations') or []) or '—')}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="8">运行 ./run.sh attribution</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>每日涨跌归因 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb"><a href="../../index.html">首页</a> / <a href="../index.html">报表列表</a> / 每日归因</nav>
      <h1 class="site-title">每日涨跌归因</h1>
      <p class="site-subtitle">对比昨日与今日的涨跌事实，解释上涨延续或下跌破坏的主要原因</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>股票</th><th>昨日表现</th><th>昨日主因</th><th>今日表现</th><th>今日主因</th><th>逻辑破坏</th><th>观察位</th><th>限制</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payloads = load_payloads()
    out = REPORTS_DIR / "index.html"
    out.write_text(render(payloads), encoding="utf-8")
    print(f"[gen_attribution_report] 已生成 {out} ({len(payloads)} 只)")


if __name__ == "__main__":
    main()
