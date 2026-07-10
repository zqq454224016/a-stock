#!/usr/bin/env python3
"""生成短中长线推荐报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "recommendations" / "summary.json"
REPORTS_DIR = ROOT / "reports" / "recommendations"

STATUS = {"recommended": "推荐", "watch": "观察", "excluded": "排除"}
LIMITATIONS = {
    "recommendation_universe_limited_to_local_watchlist": "推荐范围仅限本地自选股，不代表全市场扫描结果。",
    "long_horizon_lacks_dedicated_prediction_model": "长线暂缺专用预测模型，主要依据因子、估值、事件和长期趋势。",
    "degraded_market_or_fund_flow_data_may_reduce_confidence": "大盘或资金数据处于降级状态，推荐置信度需下调。",
}


def _read() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8")) if DATA_PATH.exists() else {}


def _rows(items: list[dict]) -> str:
    return "".join(f"""
      <tr><td>{x.get('code')}</td><td>{x.get('name')}</td><td>{x.get('score')}</td>
      <td>{STATUS.get(x.get('status'), x.get('status'))}</td>
      <td>{'；'.join(x.get('evidence') or [])}</td><td>{'；'.join(x.get('risks') or ['—'])}</td>
      <td>{'；'.join(x.get('invalidation_conditions') or [])}</td>
      <td>{'；'.join(x.get('reevaluation_conditions') or [])}</td></tr>""" for x in items)


def render(payload: dict) -> str:
    market = payload.get("market_context") or {}
    sections: list[str] = []
    for result in (payload.get("periods") or {}).values():
        all_rows = _rows(result.get("evaluated") or [])
        if not all_rows:
            all_rows = '<tr><td colspan="8">暂无可评估股票</td></tr>'
        shortage = result.get("shortage_reason") or "推荐数量已达到上限"
        sections.append(f"""
    <section class="table-section">
      <h2>{result.get('label')}（{result.get('horizon')}）</h2>
      <p>{shortage}</p>
      <table class="data-table"><thead><tr><th>代码</th><th>名称</th><th>评分</th><th>状态</th>
      <th>证据</th><th>风险</th><th>推荐失效条件</th><th>重新评估条件</th></tr></thead><tbody>{all_rows}</tbody></table>
    </section>""")
    limitation_rows = "".join(f"<li>{LIMITATIONS.get(x, x)}</li>" for x in payload.get("limitations") or [])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>短中长线推荐 · A股全景</title>
<link rel="stylesheet" href="../../css/common.css"><link rel="stylesheet" href="../../css/report.css"></head>
<body><header class="site-header"><div class="container"><h1 class="site-title">短中长线推荐</h1>
<p class="site-subtitle">按周期独立评分，未通过风险门禁时不强行凑满 5 支</p></div></header>
<main class="container report-body">
  <section class="summary-grid">
    <div class="summary-card"><span>市场状态</span><strong>{market.get('regime') or '—'}</strong></div>
    <div class="summary-card"><span>主要指数平均涨跌</span><strong>{market.get('index_avg_change_pct', 0):.2f}%</strong></div>
    <div class="summary-card"><span>主力资金净额</span><strong>{market.get('main_net_yi', 0):.2f}亿</strong></div>
    <div class="summary-card"><span>数据状态</span><strong>{'降级' if market.get('degraded') else '正常'}</strong></div>
  </section>
  {''.join(sections)}
  <section class="table-section"><h2>使用边界</h2><ul>{limitation_rows}</ul></section>
</main></body></html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(_read()), encoding="utf-8")
    print(f"[gen_recommendation_report] 已生成 {out}")


if __name__ == "__main__":
    main()
