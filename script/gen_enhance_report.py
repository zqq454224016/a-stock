#!/usr/bin/env python3
"""生成数据增强汇总页（P1-3）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENHANCE_DIR = ROOT / "assets" / "data" / "enhance"
INDICES_DIR = ROOT / "assets" / "data" / "indices"
REPORTS_DIR = ROOT / "reports" / "enhance"


def _translate_limits(items: list[str] | None) -> str:
    sys.path.insert(0, str(ROOT))
    from quant_system.utils.i18n_labels import translate_limitations
    return translate_limitations(items)


def load_rows() -> tuple[list[dict], dict]:
    index_path = ENHANCE_DIR / "index.json"
    rows: list[dict] = []
    meta = {}
    if index_path.exists():
        meta = json.loads(index_path.read_text(encoding="utf-8"))
        rows = meta.get("stocks", [])
    else:
        for path in ENHANCE_DIR.glob("*.json"):
            if path.stem == "index":
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            from quant_system.pipeline.enhance_builder import summarize_enhance
            rows.append(summarize_enhance(data))
    benchmarks = {}
    bench_path = INDICES_DIR / "benchmarks.json"
    if bench_path.exists():
        benchmarks = json.loads(bench_path.read_text(encoding="utf-8"))
    return rows, {**meta, "benchmarks": benchmarks}


def render(rows: list[dict], meta: dict) -> str:
    updated = meta.get("updated_at", "")
    bench = meta.get("benchmarks") or {}
    bench_rows = []
    for i in bench.get("indices") or []:
        pct = i.get("change_pct")
        cls = "text-up" if (pct or 0) >= 0 else "text-down"
        bench_rows.append(
            f"<tr><td>{i.get('name','')}</td><td>{i.get('code','')}</td>"
            f"<td>{i.get('close','--')}</td><td class=\"{cls}\">{pct if pct is not None else '--'}%</td></tr>"
        )
    flow = bench.get("fund_flow") or {}
    body = []
    for r in rows:
        limits = _translate_limits(r.get("limitations"))
        body.append(f"""
        <tr>
          <td><a href="../stock/{r['code']}.html">{r['code']}</a></td>
          <td>{r.get('name') or ''}</td>
          <td>{r.get('trade_date', '')}</td>
          <td>{r.get('pe_ttm', '--')}</td>
          <td>{r.get('pb', '--')}</td>
          <td>{r.get('market_cap_yi', '--')}</td>
          <td>{r.get('north_hold_pct', '--')}</td>
          <td>{r.get('north_net_buy_yi', '--')}</td>
          <td>{r.get('next_lockup') or '—'}</td>
          <td style="font-size:0.85rem">{limits}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>数据增强 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        数据增强
      </nav>
      <h1 class="site-title">数据增强 <span class="stock-code">P1-3</span></h1>
      <p class="site-subtitle">估值 · 公司行为 · 北向/两融 · 指数对照 · 更新于 {updated}</p>
    </div>
  </header>
  <main class="container">
    <section class="panel">
      <h2>大盘指数与资金</h2>
      <p>交易日 {bench.get('trade_date', '--')} · 北向净买 {flow.get('north_net', '--')} 亿 · 主力净流 {flow.get('main_net', '--')} 亿</p>
      <table class="data-table">
        <thead><tr><th>指数</th><th>代码</th><th>收盘</th><th>涨跌幅</th></tr></thead>
        <tbody>{''.join(bench_rows) or '<tr><td colspan="4">暂无指数快照，请先运行 ./run.sh market</td></tr>'}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>自选股增强摘要</h2>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th><th>名称</th><th>日期</th><th>PE(TTM)</th><th>PB</th>
            <th>总市值(亿)</th><th>北向持股%</th><th>北向净买(亿)</th><th>下次解禁</th><th>限制</th>
          </tr>
        </thead>
        <tbody>{''.join(body) or '<tr><td colspan="10">暂无数据，请运行 ./run.sh enhance</td></tr>'}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def main() -> None:
    sys.path.insert(0, str(ROOT))
    rows, meta = load_rows()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html = render(rows, meta)
    out = REPORTS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"已生成 {out}")


if __name__ == "__main__":
    main()
