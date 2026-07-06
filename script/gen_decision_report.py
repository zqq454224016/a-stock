#!/usr/bin/env python3
"""生成单股指导性决策看板。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "decisions"
REPORTS_DIR = ROOT / "reports" / "decision"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_decisions() -> list[dict]:
    index = _read_json(DATA_DIR / "index.json")
    rows = index.get("decisions") or []
    decisions = []
    if rows:
        for row in rows:
            path = DATA_DIR / f"{row.get('code')}.json"
            if path.exists():
                decisions.append(_read_json(path))
    else:
        for path in sorted(DATA_DIR.glob("*.json")):
            if path.stem != "index":
                decisions.append(_read_json(path))
    return decisions


def _action_label(action: str) -> str:
    return {
        "buy": "买入",
        "hold": "持有",
        "reduce": "减仓",
        "sell": "卖出",
        "watch": "观望",
    }.get(action, action)


def _action_class(action: str) -> str:
    if action == "buy":
        return "text-up"
    if action in ("sell", "reduce"):
        return "text-down"
    return ""


def _pct(value: float | int | None) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def _list(items: list[str]) -> str:
    return "".join(f"<li>{x}</li>" for x in (items or ["—"]))


def render_index(decisions: list[dict]) -> str:
    rows = "".join(
        f"""
        <tr>
          <td><a href="{d.get('code')}.html">{d.get('code')}</a></td>
          <td>{d.get('name') or ''}</td>
          <td class="{_action_class(d.get('action',''))}">{_action_label(d.get('action',''))}</td>
          <td>{_pct(d.get('position_suggestion'))}</td>
          <td>{d.get('confidence')}</td>
          <td>{'是' if d.get('requires_human_review') else '否'}</td>
          <td>{'; '.join((d.get('reasons') or [])[:2])}</td>
        </tr>"""
        for d in decisions
    ) or '<tr><td colspan="7">运行 python quant_system/main.py decision</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>操作建议 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">单股操作建议</h1>
      <p class="site-subtitle">Decision Engine · 指导性优先 · 非自动交易</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>动作</th><th>建议仓位</th><th>置信度</th><th>人工复核</th><th>核心理由</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">操作建议仅供研究与模拟交易，不构成投资建议。</p>
  </main>
</body>
</html>"""


def render_detail(d: dict) -> str:
    ev = d.get("evidence") or {}
    pred = ev.get("prediction") or {}
    position = ev.get("position") or {}
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{d.get('code')} 操作建议 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">{d.get('name')} ({d.get('code')})</h1>
      <p class="site-subtitle">操作建议：<strong class="{_action_class(d.get('action',''))}">{_action_label(d.get('action',''))}</strong> · 建议仓位 {_pct(d.get('position_suggestion'))}</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="summary-grid">
      <div class="summary-card"><span>动作</span><strong>{_action_label(d.get('action',''))}</strong></div>
      <div class="summary-card"><span>建议仓位</span><strong>{_pct(d.get('position_suggestion'))}</strong></div>
      <div class="summary-card"><span>置信度</span><strong>{d.get('confidence')}</strong></div>
      <div class="summary-card"><span>预测方向</span><strong>{pred.get('direction','—')}</strong></div>
      <div class="summary-card"><span>预测概率</span><strong>{_pct(pred.get('probability'))}</strong></div>
      <div class="summary-card"><span>因子分</span><strong>{ev.get('factor_score','—')}</strong></div>
    </section>

    <section class="table-section">
      <h2>理由</h2>
      <ul>{_list(d.get('reasons') or [])}</ul>
    </section>
    <section class="table-section">
      <h2>风险</h2>
      <ul>{_list(d.get('risks') or [])}</ul>
    </section>
    <section class="table-section">
      <h2>失效条件</h2>
      <ul>{_list(d.get('invalid_conditions') or [])}</ul>
    </section>
    <section class="table-section">
      <h2>持仓上下文</h2>
      <table class="data-table">
        <tbody>
          <tr><th>股数</th><td>{position.get('shares', 0)}</td></tr>
          <tr><th>浮盈亏率</th><td>{position.get('unrealized_pnl_pct', 0)}%</td></tr>
          <tr><th>市值</th><td>{position.get('market_value') or 0}</td></tr>
        </tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">{d.get('disclaimer','')}</p>
  </main>
</body>
</html>"""


def main() -> None:
    decisions = load_decisions()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "index.html").write_text(render_index(decisions), encoding="utf-8")
    for d in decisions:
        code = d.get("code")
        if code:
            (REPORTS_DIR / f"{code}.html").write_text(render_detail(d), encoding="utf-8")
    print(f"[gen_decision_report] 已生成 {REPORTS_DIR} ({len(decisions)} 只)")


if __name__ == "__main__":
    main()
