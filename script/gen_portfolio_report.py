#!/usr/bin/env python3
"""生成组合管理报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "portfolio" / "summary.json"
REPORTS_DIR = ROOT / "reports" / "portfolio"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _money(value) -> str:
    return f"{float(value or 0):,.2f}"


def _pct(value) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def _ret(value) -> str:
    return f"{float(value or 0):.2f}%"


def _market_label(value: str) -> str:
    return {
        "SH": "沪市",
        "SZ": "深市",
        "BJ": "北交所",
        "UNKNOWN": "未知",
    }.get(value, value or "—")


def _action_label(value: str) -> str:
    return {
        "buy": "买入",
        "hold": "持有",
        "reduce": "减仓",
        "sell": "卖出",
        "watch": "观望",
    }.get(value, value or "—")


def _confidence_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value or "—")


def _level_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, value or "—")


def _style_label(items: list[str]) -> str:
    return "、".join(items or ["—"])


def render(payload: dict) -> str:
    s = payload.get("summary") or {}
    positions = payload.get("positions") or []
    targets = payload.get("target_positions") or []
    alerts = payload.get("risk_alerts") or []
    exposures = payload.get("exposures") or {}
    rebalance = payload.get("rebalance_plan") or []
    pos_rows = "".join(f"""
        <tr>
          <td>{p.get('code')}</td><td>{p.get('name')}</td><td>{_market_label(p.get('market'))}</td><td>{p.get('industry') or '—'}</td>
          <td>{p.get('shares')}</td><td>{_money(p.get('market_value'))}</td><td>{_pct(p.get('weight'))}</td>
          <td>{_style_label(p.get('styles') or [])}</td><td>{_ret(p.get('unrealized_pnl_pct'))}</td><td>{_pct(p.get('target_weight'))}</td><td>{_pct(p.get('rebalance_gap'))}</td>
        </tr>""" for p in positions) or '<tr><td colspan="11">暂无持仓</td></tr>'
    target_rows = "".join(f"""
        <tr>
          <td>{t.get('code')}</td><td>{t.get('name')}</td><td>{t.get('industry') or '—'}</td><td>{_action_label(t.get('decision_action'))}</td>
          <td>{_confidence_label(t.get('decision_confidence'))}</td><td>{_pct(t.get('current_weight'))}</td>
          <td>{_pct(t.get('target_weight'))}</td><td>{_pct(t.get('rebalance_gap'))}</td>
          <td>{'是' if t.get('requires_human_review') else '否'}</td>
        </tr>""" for t in targets) or '<tr><td colspan="9">暂无目标仓位</td></tr>'
    alert_rows = "".join(f"""
        <tr><td>{_level_label(a.get('level'))}</td><td>{a.get('message')}</td></tr>""" for a in alerts) or '<tr><td colspan="2">暂无账户级风险告警</td></tr>'
    exposure_rows = "".join(
        f"<tr><td>{_market_label(k)}</td><td>{_pct(v)}</td><td>{_pct((exposures.get('target_by_market') or {}).get(k, 0))}</td></tr>"
        for k, v in (exposures.get("by_market") or {}).items()
    ) or '<tr><td colspan="3">暂无市场暴露</td></tr>'
    industry_keys = sorted(set((exposures.get("by_industry") or {}) ) | set((exposures.get("target_by_industry") or {})))
    industry_rows = "".join(
        f"<tr><td>{k}</td><td>{_pct((exposures.get('by_industry') or {}).get(k, 0))}</td><td>{_pct((exposures.get('target_by_industry') or {}).get(k, 0))}</td></tr>"
        for k in industry_keys
    ) or '<tr><td colspan="3">暂无行业暴露</td></tr>'
    style_keys = sorted(set((exposures.get("by_style") or {}) ) | set((exposures.get("target_by_style") or {})))
    style_rows = "".join(
        f"<tr><td>{k}</td><td>{_pct((exposures.get('by_style') or {}).get(k, 0))}</td><td>{_pct((exposures.get('target_by_style') or {}).get(k, 0))}</td></tr>"
        for k in style_keys
    ) or '<tr><td colspan="3">暂无风格暴露</td></tr>'
    rebalance_rows = "".join(f"""
        <tr><td>{r.get('code')}</td><td>{r.get('name')}</td><td>{r.get('action')}</td><td>{_pct(r.get('rebalance_gap'))}</td><td>{r.get('priority')}</td><td>{'是' if r.get('requires_human_review') else '否'}</td><td>{r.get('reason')}</td></tr>
        """ for r in rebalance) or '<tr><td colspan="7">暂无调仓计划</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>组合管理 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">组合管理</h1>
      <p class="site-subtitle">账户净值、现金、持仓集中度、目标仓位和组合风险</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="summary-grid">
      <div class="summary-card"><span>总权益</span><strong>{_money(s.get('total_equity'))}</strong></div>
      <div class="summary-card"><span>现金</span><strong>{_money(s.get('cash'))}</strong></div>
      <div class="summary-card"><span>持仓市值</span><strong>{_money(s.get('market_value'))}</strong></div>
      <div class="summary-card"><span>总收益</span><strong>{_ret(s.get('total_return_pct'))}</strong></div>
      <div class="summary-card"><span>现金占比</span><strong>{_pct(s.get('cash_weight'))}</strong></div>
      <div class="summary-card"><span>调仓项</span><strong>{s.get('rebalance_count') or 0}</strong></div>
      <div class="summary-card"><span>风险告警</span><strong>{s.get('risk_alert_count') or 0}</strong></div>
    </section>
    <section class="table-section">
      <h2>当前持仓</h2>
      <table class="data-table"><thead><tr><th>代码</th><th>名称</th><th>市场</th><th>行业</th><th>股数</th><th>市值</th><th>权重</th><th>风格</th><th>浮盈亏</th><th>目标</th><th>调仓差</th></tr></thead><tbody>{pos_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>目标仓位</h2>
      <table class="data-table"><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>决策</th><th>置信度</th><th>当前</th><th>目标</th><th>调仓差</th><th>人工复核</th></tr></thead><tbody>{target_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>调仓计划</h2>
      <table class="data-table"><thead><tr><th>代码</th><th>名称</th><th>动作</th><th>调仓差</th><th>优先级</th><th>人工复核</th><th>原因</th></tr></thead><tbody>{rebalance_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>市场暴露</h2>
      <table class="data-table"><thead><tr><th>市场</th><th>当前暴露</th><th>目标暴露</th></tr></thead><tbody>{exposure_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>行业暴露</h2>
      <table class="data-table"><thead><tr><th>行业</th><th>当前暴露</th><th>目标暴露</th></tr></thead><tbody>{industry_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>风格暴露</h2>
      <table class="data-table"><thead><tr><th>风格</th><th>当前暴露</th><th>目标暴露</th></tr></thead><tbody>{style_rows}</tbody></table>
    </section>
    <section class="table-section">
      <h2>账户级风险</h2>
      <table class="data-table"><thead><tr><th>级别</th><th>说明</th></tr></thead><tbody>{alert_rows}</tbody></table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">组合管理基于模拟账户和决策结果，不构成实盘指令。</p>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = _read(DATA_PATH)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(payload), encoding="utf-8")
    print(f"[gen_portfolio_report] 已生成 {out}")


if __name__ == "__main__":
    main()
