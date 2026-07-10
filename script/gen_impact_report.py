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


def _quality_label(level: str) -> str:
    return {
        "high": "高",
        "medium": "中",
        "low": "低",
    }.get(level, level or "—")


def _review_label(review: dict) -> str:
    status = {
        "evaluated": "已复盘",
        "pending": "待复盘",
        "missing": "缺少复盘",
        "insufficient": "样本不足",
    }.get(review.get("status"), review.get("status") or "—")
    hit_rate = review.get("hit_rate")
    hit = "—" if hit_rate is None else f"{float(hit_rate) * 100:.1f}%"
    return f"{status}<br>已评估 {review.get('evaluated_count', 0)}<br>命中率 {hit}"


def render(payloads: list[dict]) -> str:
    rows = []
    for p in payloads:
        events = p.get("events") or []
        first = events[0] if events else {}
        quality = first.get("evidence_quality") or {}
        payload_quality = p.get("evidence_quality") or {}
        rows.append(f"""
        <tr>
          <td>{p.get('code')}</td>
          <td>{p.get('name') or ''}</td>
          <td>{p.get('impact_score')}</td>
          <td>{_dir_label(p.get('impact_direction',''))}</td>
          <td>{len(events)}</td>
          <td>{first.get('title') or '—'}</td>
          <td>{'; '.join(first.get('evidence') or [])[:160]}</td>
          <td>{_quality_label(quality.get('level'))}<br>均分 {payload_quality.get('avg_score', 0)}</td>
          <td>{_review_label(p.get('post_event_review') or {})}</td>
          <td>{_limits_label(p.get('limitations'))}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="10">运行 python quant_system/main.py impact</td></tr>'
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
        <thead><tr><th>代码</th><th>名称</th><th>影响分</th><th>方向</th><th>事件数</th><th>首要事件</th><th>证据</th><th>证据质量</th><th>后验复盘</th><th>限制</th></tr></thead>
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
