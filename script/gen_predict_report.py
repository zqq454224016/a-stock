#!/usr/bin/env python3
"""生成走势预测汇总页。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRED_DIR = ROOT / "assets" / "data" / "predictions"
REPORTS_DIR = ROOT / "reports" / "predict"


def load_predictions() -> list[dict]:
    index_path = PRED_DIR / "index.json"
    if index_path.exists():
        data = json.loads(index_path.read_text(encoding="utf-8"))
        items = []
        for row in data.get("predictions", []):
            code = row["code"]
            detail_path = PRED_DIR / f"{code}.json"
            if detail_path.exists():
                items.append(json.loads(detail_path.read_text(encoding="utf-8")))
        return items
    return [json.loads(p.read_text(encoding="utf-8")) for p in PRED_DIR.glob("*.json") if p.stem != "index"]


def _dir_label(d: str) -> str:
    return {"up": "偏多 ↑", "down": "偏空 ↓", "neutral": "震荡 →"}.get(d, d)


def _conf_label(c: str) -> str:
    return {"low": "低", "medium": "中", "high": "高"}.get(c, c)


def render_index(predictions: list[dict]) -> str:
    rows = []
    for p in predictions:
        code = p["code"]
        rows.append(f"""
        <tr>
          <td><a href="../stock/{code}.html">{code}</a></td>
          <td>{p.get('horizon','')}</td>
          <td class="{'text-up' if p.get('direction')=='up' else 'text-down' if p.get('direction')=='down' else ''}">{_dir_label(p.get('direction',''))}</td>
          <td>{p.get('probability', 0) * 100:.1f}%</td>
          <td>{_conf_label(p.get('confidence',''))}</td>
          <td>{(p.get('expected_return') or 0) * 100:.2f}%</td>
          <td>{', '.join(p.get('risk_flags') or []) or '—'}</td>
        </tr>""")

    body = "".join(rows) or '<tr><td colspan="7">运行 python quant_system/main.py predict</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>走势预测 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">可验证走势预测</h1>
      <p class="site-subtitle">L2 预测 · 含回测证据 · 非确定性结论</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th><th>周期</th><th>方向</th><th>概率</th>
            <th>置信度</th><th>预期收益</th><th>风险标记</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">统计倾向仅供参考，不构成投资建议。</p>
  </main>
</body>
</html>"""


def main() -> None:
    preds = load_predictions()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render_index(preds), encoding="utf-8")
    print(f"[gen_predict_report] 已生成 {out} ({len(preds)} 只)")


if __name__ == "__main__":
    main()
