#!/usr/bin/env python3
"""生成实际影响数据看板。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "impact"
REPORTS_DIR = ROOT / "reports" / "impact"


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


def _dir_label(direction: str) -> str:
    import sys
    sys.path.insert(0, str(ROOT))
    from quant_system.utils.i18n_labels import translate_direction
    return translate_direction(direction)


def _limits_label(items: list[str] | None) -> str:
    import sys
    sys.path.insert(0, str(ROOT))
    from quant_system.utils.i18n_labels import translate_limitations
    return translate_limitations(items)


def render(payloads: list[dict]) -> str:
    rows = []
    for p in payloads:
        events = p.get("events") or []
        first = events[0] if events else {}
        rows.append(f"""
        <tr>
          <td>{p.get('code')}</td>
          <td>{p.get('name') or ''}</td>
          <td>{p.get('impact_score')}</td>
          <td>{_dir_label(p.get('impact_direction',''))}</td>
          <td>{len(events)}</td>
          <td>{first.get('title') or '—'}</td>
          <td>{'; '.join(first.get('evidence') or [])[:160]}</td>
          <td>{_limits_label(p.get('limitations'))}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="8">运行 python quant_system/main.py impact</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>实际影响数据 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">实际影响数据</h1>
      <p class="site-subtitle">业绩、估值、解禁、生产材料/产品价格等对涨跌的结构化影响</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>影响分</th><th>方向</th><th>事件数</th><th>首要事件</th><th>证据</th><th>限制</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">实际影响数据来自已采集增强数据和公司披露字段，缺失项会显式标记。</p>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payloads = load_payloads()
    out = REPORTS_DIR / "index.html"
    out.write_text(render(payloads), encoding="utf-8")
    print(f"[gen_impact_report] 已生成 {out} ({len(payloads)} 只)")


if __name__ == "__main__":
    main()
