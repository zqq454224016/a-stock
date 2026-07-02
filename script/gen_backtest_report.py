#!/usr/bin/env python3
"""根据回测 JSON 生成 HTML 报告。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = ROOT / "assets" / "data" / "backtest"
REPORTS_DIR = ROOT / "reports" / "backtest"


def load_backtest(code: str, strategy: str = "ma_cross") -> dict:
    path = BACKTEST_DIR / f"{code}_{strategy}.json"
    if not path.exists():
        raise FileNotFoundError(f"回测数据不存在: {path}，请先运行 python quant_system/main.py backtest {code}")
    return json.loads(path.read_text(encoding="utf-8"))


def render_report(data: dict) -> str:
    code = data["code"]
    strategy = data["strategy"]
    m = data["metrics"]
    cfg = data.get("config", {})

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{code} 回测报告 · {strategy}</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> / 回测
      </nav>
      <h1 class="site-title">{code} <span class="stock-code">{strategy}</span></h1>
      <p class="site-subtitle">
        策略 v{data.get('strategy_version', '')} · 数据 {data.get('data_version', '')} ·
        质量分 {data.get('quality_score', '--')} · 更新 {data.get('updated_at', '')}
      </p>
    </div>
  </header>

  <main class="container report-body">
    <section class="stats-row">
      <div class="stat-card">
        <div class="name">总收益</div>
        <div class="value">{m.get('total_return_pct', '--')}%</div>
      </div>
      <div class="stat-card">
        <div class="name">年化收益</div>
        <div class="value">{m.get('annual_return_pct', '--')}%</div>
      </div>
      <div class="stat-card">
        <div class="name">最大回撤</div>
        <div class="value">{m.get('max_drawdown_pct', '--')}%</div>
      </div>
      <div class="stat-card">
        <div class="name">夏普 / 胜率</div>
        <div class="value" style="font-size:1rem">{m.get('sharpe_ratio', '--')} / {m.get('win_rate_pct', '--')}%</div>
      </div>
    </section>

    <section class="chart-section">
      <h2>净值曲线</h2>
      <div id="equity-chart" class="chart-box chart-box-lg"></div>
    </section>

    <section class="table-section">
      <h2>交易明细</h2>
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>日期</th><th>动作</th><th>价格</th><th>数量</th>
              <th>金额</th><th>费用</th><th>盈亏</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            {''.join(_trade_row(t) for t in data.get('trades', []))}
          </tbody>
        </table>
      </div>
    </section>

    <section class="table-section">
      <h2>回测参数</h2>
      <p>初始资金 {cfg.get('initial_cash')} · 佣金 {cfg.get('commission_rate')} ·
         印花税 {cfg.get('stamp_tax_rate')} · 滑点 {cfg.get('slippage_bps')}bp</p>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"><p>回测结果不代表未来收益，仅供参考。</p></div>
  </footer>

  <script>
    const btData = {json.dumps(data, ensure_ascii=False)};
    const chart = echarts.init(document.getElementById('equity-chart'), 'dark');
    chart.setOption({{
      backgroundColor: 'transparent',
      tooltip: {{ trigger: 'axis' }},
      xAxis: {{ type: 'category', data: btData.equity_curve.map(p => p.date) }},
      yAxis: {{ scale: true }},
      series: [{{
        type: 'line', data: btData.equity_curve.map(p => p.equity),
        smooth: true, lineStyle: {{ color: '#3b82f6' }}, showSymbol: false
      }}]
    }});
  </script>
</body>
</html>"""


def _trade_row(t: dict) -> str:
    pnl = t.get("pnl", "")
    pnl_s = f"{pnl:.2f}" if isinstance(pnl, (int, float)) else "--"
    return f"""<tr>
      <td>{t.get('date','')}</td><td>{t.get('action','')}</td>
      <td>{t.get('price','')}</td><td>{t.get('shares','')}</td>
      <td>{t.get('amount','')}</td><td>{t.get('fee','')}</td>
      <td>{pnl_s}</td><td>{t.get('status','')}</td>
    </tr>"""


def main() -> None:
    index_path = BACKTEST_DIR / "index.json"
    codes: list[tuple[str, str]] = []
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        codes = [(r["code"], r.get("strategy", "ma_cross")) for r in index.get("results", [])]
    else:
        codes = [(p.stem.rsplit("_", 1)[0], p.stem.rsplit("_", 1)[1])
                 for p in BACKTEST_DIR.glob("*_*.json") if p.stem != "index"]

    if not codes:
        print("[gen_backtest_report] 无回测数据")
        return

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for code, strategy in codes:
        data = load_backtest(code, strategy)
        out = REPORTS_DIR / f"{code}_{strategy}.html"
        out.write_text(render_report(data), encoding="utf-8")
        print(f"[gen_backtest_report] 已生成 {out}")


if __name__ == "__main__":
    main()
