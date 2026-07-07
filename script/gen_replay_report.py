#!/usr/bin/env python3
"""生成历史视角滚动推演报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data" / "replay"
REPORTS_DIR = ROOT / "reports" / "replay"


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_payloads() -> list[dict]:
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
    return payloads


def _pct(value) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _ret(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}%"


def _hit_label(value) -> str:
    if value is True:
        return "命中"
    if value is False:
        return "未命中"
    return "中性"


def _list(items: list, empty: str = "—") -> str:
    if not items:
        return empty
    rows = []
    for item in items:
        if isinstance(item, dict):
            label = item.get("label") or item.get("category") or ""
            evidence = item.get("evidence") or ""
            source = item.get("source") or ""
            timing = item.get("source_timing") or ""
            meta = " · ".join(x for x in (source, timing) if x)
            suffix = f"<br><small>{meta}</small>" if meta else ""
            rows.append(f"<li>{label}<br><small>{evidence}</small>{suffix}</li>")
        else:
            rows.append(f"<li>{item}</li>")
    return "<ul>" + "".join(rows) + "</ul>"


def render_index(payloads: list[dict]) -> str:
    rows = []
    for p in payloads:
        s = p.get("summary") or {}
        rows.append(f"""
        <tr>
          <td><a href="{p.get('code')}.html">{p.get('code')}</a></td>
          <td>{p.get('name') or ''}</td>
          <td>{p.get('start_knowledge_cutoff') or '—'}</td>
          <td>{p.get('end_target_date') or '—'}</td>
          <td>{s.get('step_count') or 0}</td>
          <td>{_pct(s.get('hit_rate'))}</td>
          <td>{_ret(s.get('total_return_pct'))}</td>
          <td>{s.get('up_prediction_count') or 0}</td>
          <td>{s.get('down_prediction_count') or 0}</td>
          <td>{(p.get('learning') or {}).get('miss_count') or 0}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="10">运行 python quant_system/main.py replay</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>十日前滚动推演 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">十日前滚动推演</h1>
      <p class="site-subtitle">每一步只使用当时已知 K 线，对下一交易日做技术预测、涨跌根因分析和命中率迭代复盘</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>代码</th><th>名称</th><th>起始认知日</th><th>结束目标日</th><th>步数</th><th>命中率</th><th>区间收益</th><th>看多次数</th><th>看空次数</th><th>未命中</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def render_detail(p: dict) -> str:
    rows = []
    for step in p.get("steps") or []:
        pred = step.get("prediction") or {}
        signal = step.get("technical_signal") or {}
        actual = step.get("actual") or {}
        root = step.get("root_cause") or {}
        levels = step.get("operation_levels") or {}
        rows.append(f"""
        <tr>
          <td>{step.get('knowledge_cutoff')}</td>
          <td>{step.get('target_date')}</td>
          <td>{step.get('as_of_close')}</td>
          <td>{step.get('target_close')}</td>
          <td>{pred.get('direction')}</td>
          <td>{_pct(pred.get('probability'))}</td>
          <td>{signal.get('signal')} / {signal.get('signal_score')}</td>
          <td>{_ret(actual.get('return_pct'))}</td>
          <td>{actual.get('direction')}</td>
          <td>{_hit_label(actual.get('hit'))}</td>
          <td>{_list(root.get('actual_root_causes') or [])}</td>
          <td>{_list(root.get('miss_reasons') or [])}</td>
          <td>
            买 {levels.get('buy_trigger_price', '—')}<br>
            守 {levels.get('sell_guard_price', '—')}<br>
            止盈观察 {levels.get('take_profit_watch_price', '—')}
          </td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="13">暂无推演步骤</td></tr>'
    s = p.get("summary") or {}
    learning = p.get("learning") or {}
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{p.get('code')} 推演 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <h1 class="site-title">{p.get('name')} ({p.get('code')})</h1>
      <p class="site-subtitle">滚动推演 {p.get('start_knowledge_cutoff')} → {p.get('end_target_date')} · 命中率 {_pct(s.get('hit_rate'))}</p>
    </div>
  </header>
  <main class="container report-body">
    <section class="table-section">
      <h2>命中率迭代思考</h2>
      <p>未命中 {learning.get('miss_count', 0)} 次，看多后下跌 {learning.get('false_up_count', 0)} 次，看空后上涨 {learning.get('false_down_count', 0)} 次。</p>
      <h3>优化方向</h3>
      {_list(learning.get('hit_rate_improvement_thoughts') or [])}
      <h3>下一轮迭代重点</h3>
      {_list(learning.get('next_iteration_focus') or [])}
    </section>
    <section class="table-section">
      <table class="data-table">
        <thead><tr><th>认知截止</th><th>目标日</th><th>当时收盘</th><th>目标收盘</th><th>预测方向</th><th>概率</th><th>技术信号</th><th>真实收益</th><th>真实方向</th><th>复盘</th><th>涨跌根因</th><th>失效原因</th><th>价位雏形</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </section>
    <p style="color:var(--color-muted);font-size:0.9rem">限制：只使用技术 K 线；真实收益仅用于事后复盘，不参与当时预测。价位雏形只用于后续单日操作建议设计，不构成交易指令。</p>
  </main>
</body>
</html>"""


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payloads = load_payloads()
    (REPORTS_DIR / "index.html").write_text(render_index(payloads), encoding="utf-8")
    for payload in payloads:
        code = payload.get("code")
        if code:
            (REPORTS_DIR / f"{code}.html").write_text(render_detail(payload), encoding="utf-8")
    print(f"[gen_replay_report] 已生成 {REPORTS_DIR} ({len(payloads)} 只)")


if __name__ == "__main__":
    main()
