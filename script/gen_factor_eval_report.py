#!/usr/bin/env python3
"""生成因子有效性评估报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "assets" / "data" / "factor_eval" / "summary.json"
REPORTS_DIR = ROOT / "reports" / "factor_eval"

FACTOR_LABELS = {
    "technical_score": "技术综合分",
    "ma20_bias": "20日均线偏离",
    "rsi14": "14日强弱指标",
    "macd_hist": "指数平滑异同移动平均柱",
    "momentum_20": "20日动量",
    "volume_ratio_20": "20日量比",
    "above_ma20": "站上20日均线",
}
LIMITATION_LABELS = {
    "uses_historical_technical_proxy_samples": "当前使用历史技术因子代理样本，结果用于研究验证。",
    "pooled_time_series_not_cross_sectional_ic": "当前为小股票池时间序列混合相关性，不等同于成熟横截面因子检验。",
    "industry_neutralization_not_applied": "当前尚未完成行业和市值中性化，跨行业差异可能影响结果。",
    "sentiment_fundamental_fund_flow_need_point_in_time_history": "情绪、基本面和资金因子仍需补齐逐日历史快照后评估。",
}


def _read() -> dict:
    if not DATA_PATH.exists():
        return {}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _num(value, digits: int = 4) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _ret(value) -> str:
    return "—" if value is None else f"{float(value):.2f}%"


def render(payload: dict) -> str:
    rows: list[str] = []
    for factor, periods in (payload.get("factors") or {}).items():
        for period, result in periods.items():
            groups = (result.get("stratified") or {}).get("groups") or {}
            rows.append(f"""
        <tr><td>{FACTOR_LABELS.get(factor, factor)}</td><td>{period}</td>
        <td>{result.get('sample_count', 0)}</td><td>{_num(result.get('ic'))}</td>
        <td>{_num(result.get('rank_ic'))}</td><td>{result.get('direction') or '—'}</td>
        <td>{_ret((groups.get('低分组') or {}).get('avg_return_pct'))}</td>
        <td>{_ret((groups.get('中分组') or {}).get('avg_return_pct'))}</td>
        <td>{_ret((groups.get('高分组') or {}).get('avg_return_pct'))}</td></tr>""")
    factor_rows = "".join(rows) or '<tr><td colspan="9">暂无评估样本</td></tr>'

    drift_rows = "".join(
        f"""<tr><td>{FACTOR_LABELS.get(factor, factor)}</td><td>{_num(item.get('current'))}</td>
        <td>{_num(item.get('history_mean'))}</td><td>{_num(item.get('zscore'))}</td>
        <td>{item.get('status') or '—'}</td></tr>"""
        for factor, item in (payload.get("drift") or {}).items()
    ) or '<tr><td colspan="5">暂无漂移数据</td></tr>'
    limitations = "".join(
        f"<li>{LIMITATION_LABELS.get(item, item)}</li>" for item in (payload.get("limitations") or [])
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>因子有效性评估 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header"><div class="container">
    <h1 class="site-title">因子有效性评估</h1>
    <p class="site-subtitle">历史代理相关性、分层收益与当前因子漂移</p>
  </div></header>
  <main class="container report-body">
    <section class="summary-grid">
      <div class="summary-card"><span>股票数</span><strong>{payload.get('stock_count', 0)}</strong></div>
      <div class="summary-card"><span>历史样本数</span><strong>{payload.get('sample_count', 0)}</strong></div>
      <div class="summary-card"><span>评估周期</span><strong>{'、'.join(payload.get('horizons') or []) or '—'}</strong></div>
      <div class="summary-card"><span>评估版本</span><strong>{payload.get('factor_eval_version') or '—'}</strong></div>
    </section>
    <section class="table-section"><h2>历史有效性</h2>
      <table class="data-table"><thead><tr><th>因子</th><th>周期</th><th>样本</th>
      <th>线性相关</th><th>排序相关</th><th>方向判断</th>
      <th>低分组收益</th><th>中分组收益</th><th>高分组收益</th></tr></thead>
      <tbody>{factor_rows}</tbody></table>
    </section>
    <section class="table-section"><h2>当前漂移</h2>
      <table class="data-table"><thead><tr><th>因子</th><th>当前值</th><th>历史均值</th>
      <th>标准分</th><th>状态</th></tr></thead><tbody>{drift_rows}</tbody></table>
    </section>
    <section class="table-section"><h2>使用边界</h2><ul>{limitations}</ul></section>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "index.html"
    out.write_text(render(_read()), encoding="utf-8")
    print(f"[gen_factor_eval_report] 已生成 {out}")


if __name__ == "__main__":
    main()
