#!/usr/bin/env python3
"""生成模拟交易看板。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "trading"
REPORTS_DIR = ROOT / "reports" / "trading"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _money(v: float | int | None) -> str:
    return f"{float(v or 0):,.2f}"


def _pct(v: float | int | None) -> str:
    return f"{float(v or 0):.2f}%"


def render(account: dict, index: dict) -> str:
    summary = index.get("summary") or {}
    positions = index.get("positions") or []
    decisions = index.get("decisions") or []
    orders = (account.get("orders") or [])[-30:]

    pos_rows = "".join(
        f"""
        <tr>
          <td>{p.get('code')}</td>
          <td>{p.get('name') or ''}</td>
          <td>{p.get('shares')}</td>
          <td>{_money(p.get('avg_cost'))}</td>
          <td>{_money(p.get('last_price'))}</td>
          <td>{_money(p.get('market_value'))}</td>
          <td>{_money(p.get('unrealized_pnl'))}</td>
          <td>{_pct(p.get('unrealized_pnl_pct'))}</td>
        </tr>"""
        for p in positions
    ) or '<tr><td colspan="8">暂无持仓</td></tr>'

    decision_rows = "".join(
        f"""
        <tr>
          <td>{d.get('code')}</td>
          <td>{d.get('name') or ''}</td>
          <td>{d.get('action')}</td>
          <td>{d.get('source') or '—'}</td>
          <td>{d.get('decision_action') or '—'}</td>
          <td>{d.get('direction') or '—'}</td>
          <td>{(float(d.get('probability') or 0) * 100):.1f}%</td>
          <td>{d.get('confidence') or '—'}</td>
          <td>{_money(d.get('price'))}</td>
          <td>{d.get('reason') or '—'}</td>
        </tr>"""
        for d in decisions
    ) or '<tr><td colspan="10">暂无决策</td></tr>'

    order_rows = "".join(
        f"""
        <tr>
          <td>{o.get('created_at')}</td>
          <td>{o.get('code')}</td>
          <td>{o.get('side')}</td>
          <td>{o.get('shares')}</td>
          <td>{_money(o.get('price'))}</td>
          <td>{_money(o.get('amount'))}</td>
          <td>{_money(o.get('fee'))}</td>
          <td>{o.get('reason')}</td>
        </tr>"""
        for o in orders
    ) or '<tr><td colspan="8">暂无订单</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>模拟交易 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">模拟交易</h1>
      <p class="site-subtitle">P3-1 虚拟账户 · 基于可验证预测调仓 · 不连接券商</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="summary-grid">
      <div class="summary-card"><span>总资产</span><strong>{_money(summary.get('total_equity'))}</strong></div>
      <div class="summary-card"><span>现金</span><strong>{_money(summary.get('cash'))}</strong></div>
      <div class="summary-card"><span>持仓市值</span><strong>{_money(summary.get('market_value'))}</strong></div>
      <div class="summary-card"><span>收益率</span><strong>{_pct(summary.get('total_return_pct'))}</strong></div>
      <div class="summary-card"><span>持仓数</span><strong>{summary.get('position_count', 0)}</strong></div>
      <div class="summary-card"><span>订单数</span><strong>{summary.get('order_count', 0)}</strong></div>
    </section>

    <section class="table-section">
      <h2>当前持仓</h2>
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>市值</th><th>浮盈亏</th><th>浮盈亏率</th></tr></thead>
        <tbody>{pos_rows}</tbody>
      </table>
    </section>

    <section class="table-section">
      <h2>本轮决策</h2>
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>成交动作</th><th>来源</th><th>建议动作</th><th>预测方向</th><th>概率</th><th>置信度</th><th>价格</th><th>原因</th></tr></thead>
        <tbody>{decision_rows}</tbody>
      </table>
    </section>

    <section class="table-section">
      <h2>订单记录</h2>
      <table class="data-table">
        <thead><tr><th>时间</th><th>代码</th><th>方向</th><th>股数</th><th>价格</th><th>金额</th><th>费用</th><th>原因</th></tr></thead>
        <tbody>{order_rows}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">模拟交易仅用于研究验证，不构成投资建议，不代表真实成交。</p>
  </main>
</body>
</html>"""


def main() -> None:
    account = _read_json(DATA_DIR / "account.json")
    index = _read_json(DATA_DIR / "index.json")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(account, index), encoding="utf-8")
    print(f"[gen_trading_report] 已生成 {out}")


if __name__ == "__main__":
    main()
