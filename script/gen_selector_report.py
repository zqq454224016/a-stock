#!/usr/bin/env python3
"""生成上涨候选池报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "selector"
REPORTS_DIR = ROOT / "reports" / "selector"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows() -> list[dict]:
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
    return sorted(payloads, key=lambda x: float(x.get("upside_score") or 0), reverse=True)


def _status_class(status: str) -> str:
    if status == "candidate":
        return "text-up"
    if status == "rejected":
        return "text-down"
    return ""


def _mode_label(mode: str) -> str:
    return {
        "review": "后验复盘",
        "replay": "十日推演",
        "neutral": "默认阈值",
        "manual": "手动校准",
    }.get(mode, mode or "—")


def _list(items: list[str]) -> str:
    return "<br>".join(items or ["—"])


def _calibration(r: dict) -> str:
    calibration = r.get("calibration") or {}
    metrics = r.get("metrics") or {}
    mode = _mode_label(calibration.get("mode") or "")
    candidate = metrics.get("candidate_score_threshold")
    prob = metrics.get("probability_floor")
    return f"{mode}<br>候选 {candidate}<br>概率 {prob}"


def render(rows: list[dict]) -> str:
    body = "".join(
        f"""
        <tr>
          <td>{idx}</td>
          <td>{r.get('code')}</td>
          <td>{r.get('name') or ''}</td>
          <td>{r.get('upside_score')}</td>
          <td class="{_status_class(r.get('status',''))}">{r.get('rank_bucket')}</td>
          <td>{_list((r.get('reasons') or [])[:3])}</td>
          <td>{_list((r.get('risks') or [])[:3])}</td>
          <td>{_list(r.get('reject_reasons') or [])}</td>
          <td>{_list(r.get('candidate_blockers') or [])}</td>
          <td>{_calibration(r)}</td>
          <td>{_list((r.get('next_triggers') or [])[:3])}</td>
        </tr>"""
        for idx, r in enumerate(rows, 1)
    ) or '<tr><td colspan="11">运行 python quant_system/main.py selector</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>上涨候选池 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">上涨候选池</h1>
      <p class="site-subtitle">综合预测、因子、趋势、回测、实际影响和风险过滤的排序</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>上涨分</th><th>分层</th><th>正面依据</th><th>风险</th><th>排除原因</th><th>候选阻断</th><th>校准</th><th>进入候选触发</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">候选池用于研究和复盘，不构成投资建议。“上涨候选”表示进入候选池，“观察候选”表示等待更多确认。</p>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    out = REPORTS_DIR / "index.html"
    out.write_text(render(rows), encoding="utf-8")
    print(f"[gen_selector_report] 已生成 {out} ({len(rows)} 只)")


if __name__ == "__main__":
    main()
