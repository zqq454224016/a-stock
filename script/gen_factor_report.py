#!/usr/bin/env python3
"""生成自选股多因子排名页。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FACTORS_DIR = ROOT / "assets" / "data" / "factors"
REPORTS_DIR = ROOT / "reports" / "factors"


def load_factor_rows() -> list[dict]:
    index_path = FACTORS_DIR / "index.json"
    rows: list[dict] = []
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for item in index.get("stocks", []):
            code = item["code"]
            detail_path = FACTORS_DIR / f"{code}.json"
            if not detail_path.exists():
                continue
            data = json.loads(detail_path.read_text(encoding="utf-8"))
            f = data.get("factors", {})
            rows.append({
                "code": code,
                "trade_date": data.get("trade_date", ""),
                **f,
            })
        return rows

    for path in FACTORS_DIR.glob("*.json"):
        if path.stem == "index":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        f = data.get("factors", {})
        rows.append({"code": data.get("code", path.stem), "trade_date": data.get("trade_date", ""), **f})
    return rows


def render(rows: list[dict]) -> str:
    sorted_rows = sorted(rows, key=lambda r: r.get("multi_factor_score") or 0, reverse=True)
    body = []
    for i, r in enumerate(sorted_rows, 1):
        sent = r.get("sentiment_score")
        fund = r.get("fundamental_score")
        flow = r.get("fund_flow_score")
        sent_s = f"{sent:.1f}" if sent is not None else "--"
        fund_s = f"{fund:.1f}" if fund is not None else "--"
        flow_s = f"{flow:.1f}" if flow is not None else "--"
        body.append(f"""
        <tr>
          <td>{i}</td>
          <td><a href="../stock/{r['code']}.html">{r['code']}</a></td>
          <td>{r.get('trade_date', '')}</td>
          <td><strong>{r.get('multi_factor_score', '--')}</strong></td>
          <td>{r.get('technical_score', '--')}</td>
          <td>{sent_s}</td>
          <td>{fund_s}</td>
          <td>{flow_s}</td>
          <td>{r.get('rsi14', '--')}</td>
          <td>{r.get('momentum_20', '--')}</td>
          <td>{r.get('ma_cross', '--')}</td>
        </tr>""")

    tbody = "".join(body) or '<tr><td colspan="11">运行 ./run.sh factor</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>多因子排名 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        多因子排名
      </nav>
      <h1 class="site-title">多因子排名</h1>
      <p class="site-subtitle">技术 50% + 情绪 25% + 基本面 15% + 资金 10%（缺失项自动重分配）</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead>
          <tr>
            <th>#</th><th>代码</th><th>交易日</th><th>综合分</th>
            <th>技术分</th><th>情绪分</th><th>基本面</th><th>资金</th>
            <th>RSI</th><th>20日动量</th><th>MA交叉</th>
          </tr>
        </thead>
        <tbody>{tbody}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">综合分仅供研究对比，不构成投资建议。</p>
    <p><a href="../index.html">返回报表列表</a></p>
  </main>
</body>
</html>"""


def main() -> None:
    rows = load_factor_rows()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(rows), encoding="utf-8")
    print(f"[gen_factor_report] 已生成 {out} ({len(rows)} 只)")


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    main()
