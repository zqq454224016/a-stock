#!/usr/bin/env python3
"""生成统一 Web 控制台。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
REPORTS_DIR = ROOT / "reports" / "console"


def _read_json(rel: str, default: Any) -> Any:
    path = DATA_DIR / rel
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_map(folder: str) -> dict[str, dict[str, Any]]:
    base = DATA_DIR / folder
    if not base.exists():
        return {}
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(base.glob("*.json"))
        if path.stem != "index"
    }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _by_code(rows: list[dict[str, Any]], code_key: str = "code") -> dict[str, dict[str, Any]]:
    return {str(row.get(code_key)): row for row in rows if row.get(code_key)}


def _recommendation_status(recommendations: dict[str, Any], code: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for period_key, period in (recommendations.get("periods") or {}).items():
        for item in period.get("evaluated") or []:
            if item.get("code") == code:
                out[period_key] = item.get("status", "excluded")
                break
    return out


def _risk_level(*, selector: dict[str, Any], decision: dict[str, Any], review: dict[str, Any], replay: dict[str, Any]) -> str:
    if selector.get("status") == "rejected" or decision.get("action") in ("sell", "reduce"):
        return "高"
    if _f(review.get("worst_adverse_pct")) <= -8 or _f(replay.get("hit_rate")) < 0.3:
        return "中"
    return "低"


def build_console_payload() -> dict[str, Any]:
    stocks_index = _read_json("stocks/index.json", {})
    selector_index = _read_json("selector/index.json", {})
    decisions_index = _read_json("decisions/index.json", {})
    predictions_index = _read_json("predictions/index.json", {})
    review_index = _read_json("review/index.json", {})
    replay_index = _read_json("replay/index.json", {})
    agent_index = _read_json("agent/index.json", {})
    recommendations = _read_json("recommendations/summary.json", {})
    portfolio = _read_json("portfolio/summary.json", {})
    framework = _read_json("framework/snapshot.json", {})
    market = _read_json("latest.json", {})

    selectors = _by_code(selector_index.get("items") or [])
    decisions = _by_code(decisions_index.get("decisions") or [])
    predictions = _by_code(predictions_index.get("predictions") or [])
    reviews = _by_code(review_index.get("items") or [])
    replays = _by_code(replay_index.get("items") or [])
    agents = _by_code(agent_index.get("reports") or [])

    rows: list[dict[str, Any]] = []
    for stock in stocks_index.get("stocks") or []:
        code = str(stock.get("code"))
        selector = selectors.get(code, {})
        decision = decisions.get(code, {})
        prediction = predictions.get(code, {})
        review = reviews.get(code, {})
        replay = replays.get(code, {})
        agent = agents.get(code, {})
        rec = _recommendation_status(recommendations, code)
        rows.append({
            "code": code,
            "name": stock.get("name") or code,
            "trade_date": stock.get("trade_date") or prediction.get("trade_date") or "",
            "close": _f(stock.get("close")),
            "change_pct": _f(stock.get("change_pct")),
            "quality_score": _f(stock.get("quality_score"), 0),
            "selector_status": selector.get("rank_bucket") or selector.get("status") or "缺失",
            "selector_score": _f(selector.get("upside_score")),
            "decision_action": decision.get("action", "缺失"),
            "target_position": _f(decision.get("position_suggestion")),
            "prediction_direction": prediction.get("direction", "缺失"),
            "prediction_probability": _f(prediction.get("probability"), 0.5),
            "review_hit_rate": _f(review.get("hit_rate")),
            "replay_hit_rate": _f(replay.get("hit_rate")),
            "agent_summary": agent.get("summary", "缺失"),
            "agent_provider": agent.get("provider", "缺失"),
            "risk_level": _risk_level(selector=selector, decision=decision, review=review, replay=replay),
            "recommendation": rec,
            "links": {
                "stock": f"../stock/{code}.html",
                "agent": f"../agent/{code}.html",
                "decision": "../decision/index.html",
                "selector": "../selector/index.html",
                "replay": "../replay/index.html",
                "review": "../review/index.html",
            },
        })

    risk_counts = {"高": 0, "中": 0, "低": 0}
    for row in rows:
        risk_counts[row["risk_level"]] = risk_counts.get(row["risk_level"], 0) + 1

    return {
        "updated_at": max(
            [
                str(x)
                for x in [
                    stocks_index.get("updated_at"),
                    selector_index.get("updated_at"),
                    decisions_index.get("updated_at"),
                    agent_index.get("updated_at"),
                    framework.get("updated_at"),
                ]
                if x
            ],
            default="",
        ),
        "market": {
            "trade_date": market.get("trade_date"),
            "degraded": bool(market.get("degraded")),
            "indices": market.get("indices") or [],
            "fund_flow": market.get("fund_flow") or {},
        },
        "summary": {
            "stock_count": len(rows),
            "candidate_count": sum(1 for row in rows if row["selector_status"] == "上涨候选"),
            "buy_count": sum(1 for row in rows if row["decision_action"] == "buy"),
            "risk_counts": risk_counts,
            "portfolio_equity": (portfolio.get("summary") or {}).get("total_equity"),
            "framework_signals": (framework.get("coverage") or {}).get("signal_count"),
        },
        "rows": rows,
        "module_links": [
            {"title": "短中长线推荐", "href": "../recommendations/index.html"},
            {"title": "模块化框架", "href": "../framework/index.html"},
            {"title": "Agent 看板", "href": "../agent/index.html"},
            {"title": "组合管理", "href": "../portfolio/index.html"},
            {"title": "监控告警", "href": "../monitoring/index.html"},
            {"title": "v3 路线", "href": "../planning/v3.html"},
            {"title": "后验复盘", "href": "../review/index.html"},
            {"title": "十日推演", "href": "../replay/index.html"},
            {"title": "每日归因", "href": "../attribution/index.html"},
        ],
    }


def _json_script(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    market = payload.get("market") or {}
    indices = market.get("indices") or []
    index_line = "；".join(
        f"{html.escape(str(x.get('name')))} {html.escape(str(x.get('change_pct')))}%"
        for x in indices[:4]
    ) or "暂无指数"
    module_links = "".join(
        f'<a class="console-link" href="{html.escape(x["href"])}">{html.escape(x["title"])}</a>'
        for x in payload.get("module_links") or []
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>统一控制台 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
  <style>
    .console-toolbar {{ display:grid; grid-template-columns: minmax(180px, 1fr) 160px 160px 160px; gap:.75rem; margin:1.25rem 0; }}
    .console-link-row {{ display:flex; flex-wrap:wrap; gap:.5rem; margin:1rem 0 1.5rem; }}
    .console-link {{ border:1px solid var(--color-border); border-radius:var(--radius); padding:.45rem .7rem; background:var(--color-surface); }}
    .status-pill {{ display:inline-block; min-width:3.5rem; text-align:center; border-radius:4px; padding:.15rem .4rem; background:var(--color-border); color:var(--color-text); }}
    .risk-high {{ color:#fca5a5; }} .risk-mid {{ color:#fbbf24; }} .risk-low {{ color:#86efac; }}
    .console-table th {{ cursor:pointer; user-select:none; }}
    .console-table td {{ vertical-align:top; }}
    .console-actions a {{ margin-right:.45rem; white-space:nowrap; }}
    @media (max-width: 820px) {{ .console-toolbar {{ grid-template-columns: 1fr 1fr; }} }}
    @media (max-width: 560px) {{ .console-toolbar {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb"><a href="../../index.html">首页</a> / <a href="../index.html">报表列表</a> / 统一控制台</nav>
      <h1 class="site-title">统一控制台</h1>
      <p class="site-subtitle">交易日 {html.escape(str(market.get('trade_date') or '—'))} · {index_line}</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="stats-row">
      <div class="stat-card"><div class="name">股票数量</div><div class="value">{summary.get('stock_count', 0)}</div></div>
      <div class="stat-card"><div class="name">上涨候选</div><div class="value">{summary.get('candidate_count', 0)}</div></div>
      <div class="stat-card"><div class="name">买入建议</div><div class="value">{summary.get('buy_count', 0)}</div></div>
      <div class="stat-card"><div class="name">标准信号</div><div class="value">{summary.get('framework_signals') or 0}</div></div>
    </section>
    <div class="console-link-row">{module_links}</div>
    <section class="table-section">
      <h2>股票证据链</h2>
      <div class="console-toolbar">
        <input id="console-search" class="search-input" type="search" placeholder="搜索代码、名称、结论">
        <select id="risk-filter" class="select-input"><option value="all">全部风险</option><option value="高">高风险</option><option value="中">中风险</option><option value="低">低风险</option></select>
        <select id="action-filter" class="select-input"><option value="all">全部动作</option><option value="buy">买入</option><option value="hold">持有</option><option value="watch">观察</option><option value="reduce">减仓</option><option value="sell">卖出</option><option value="缺失">缺失</option></select>
        <select id="period-filter" class="select-input"><option value="all">全部周期</option><option value="short">短线推荐</option><option value="medium">中线推荐</option><option value="long">长线推荐</option></select>
      </div>
      <div class="table-wrap">
        <table class="data-table console-table">
          <thead><tr>
            <th data-sort="code">代码</th><th data-sort="selector_score">候选</th><th data-sort="prediction_probability">预测</th>
            <th data-sort="target_position">操作</th><th data-sort="replay_hit_rate">复盘</th><th data-sort="risk_level">风险</th><th>Agent</th><th>证据链</th>
          </tr></thead>
          <tbody id="console-rows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script id="console-data" type="application/json">{_json_script(payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById('console-data').textContent);
    let rows = [...payload.rows];
    let sortKey = 'selector_score';
    let sortDir = -1;
    const tbody = document.getElementById('console-rows');
    const riskClass = (v) => v === '高' ? 'risk-high' : v === '中' ? 'risk-mid' : 'risk-low';
    const fmtPct = (v) => Number.isFinite(Number(v)) ? (Number(v) * 100).toFixed(0) + '%' : '—';
    const fmtNum = (v, n=2) => Number.isFinite(Number(v)) ? Number(v).toFixed(n) : '—';
    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
    }}
    function rowMatches(row) {{
      const q = document.getElementById('console-search').value.trim().toLowerCase();
      const risk = document.getElementById('risk-filter').value;
      const action = document.getElementById('action-filter').value;
      const period = document.getElementById('period-filter').value;
      const hay = `${{row.code}} ${{row.name}} ${{row.agent_summary}} ${{row.selector_status}} ${{row.decision_action}}`.toLowerCase();
      if (q && !hay.includes(q)) return false;
      if (risk !== 'all' && row.risk_level !== risk) return false;
      if (action !== 'all' && row.decision_action !== action) return false;
      if (period !== 'all' && row.recommendation[period] !== 'recommended') return false;
      return true;
    }}
    function renderRows() {{
      const filtered = rows.filter(rowMatches).sort((a, b) => {{
        const av = a[sortKey], bv = b[sortKey];
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
        return String(av).localeCompare(String(bv), 'zh-CN') * sortDir;
      }});
      tbody.innerHTML = filtered.map(row => `
        <tr>
          <td><strong>${{escapeHtml(row.name)}}</strong><br><span class="stock-code">${{escapeHtml(row.code)}}</span></td>
          <td><span class="status-pill">${{escapeHtml(row.selector_status)}}</span><br>${{fmtNum(row.selector_score, 1)}}分</td>
          <td>${{escapeHtml(row.prediction_direction)}}<br>${{fmtPct(row.prediction_probability)}}</td>
          <td>${{escapeHtml(row.decision_action)}}<br>目标仓位 ${{fmtPct(row.target_position)}}</td>
          <td>推演 ${{fmtPct(row.replay_hit_rate)}}<br>后验 ${{fmtPct(row.review_hit_rate)}}</td>
          <td class="${{riskClass(row.risk_level)}}">${{escapeHtml(row.risk_level)}}</td>
          <td>${{escapeHtml(row.agent_summary)}}<br><span class="stock-code">${{escapeHtml(row.agent_provider)}}</span></td>
          <td class="console-actions">
            <a href="${{row.links.stock}}">个股</a><a href="${{row.links.agent}}">Agent</a><a href="${{row.links.selector}}">候选</a><a href="${{row.links.replay}}">推演</a><a href="${{row.links.review}}">复盘</a>
          </td>
        </tr>`).join('') || '<tr><td colspan="8">无匹配股票</td></tr>';
    }}
    document.querySelectorAll('.console-toolbar input, .console-toolbar select').forEach(el => el.addEventListener('input', renderRows));
    document.querySelectorAll('.console-table th[data-sort]').forEach(th => th.addEventListener('click', () => {{
      const key = th.dataset.sort;
      sortDir = sortKey === key ? sortDir * -1 : -1;
      sortKey = key;
      renderRows();
    }}));
    renderRows();
  </script>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_console_payload()
    out = REPORTS_DIR / "index.html"
    out.write_text(render(payload), encoding="utf-8")
    print(f"[gen_console_report] 已生成 {out} ({len(payload.get('rows') or [])} 只)")


if __name__ == "__main__":
    main()
