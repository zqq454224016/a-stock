#!/usr/bin/env python3
"""根据 JSON 数据自动渲染 HTML 报表，存入 reports/ 目录。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "assets" / "data" / "latest.json"
REPORTS_DIR = ROOT / "reports"


def load_data() -> dict:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"数据文件不存在: {DATA_FILE}，请先运行 fetch_data.py")
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def date_slug(trade_date: str) -> str:
    return trade_date.replace("-", "")


def render_daily_report(data: dict) -> str:
    slug = date_slug(data["trade_date"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data['trade_date']} 每日行情 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        每日行情
      </nav>
      <h1 class="site-title">{data['trade_date']} 每日行情</h1>
      <p class="site-subtitle">交易日：{data['trade_date']} · 更新于 {data['updated_at']}</p>
    </div>
  </header>

  <main class="container report-body">
    <section class="stats-row" id="index-stats"></section>
    <section class="chart-section">
      <h2>主要指数</h2>
      <div id="index-chart" class="chart-box"></div>
    </section>
    <section class="chart-section">
      <h2>涨跌分布</h2>
      <div id="distribution-chart" class="chart-box chart-box-sm"></div>
    </section>
    <section class="table-section">
      <h2>涨幅榜 TOP 10</h2>
      <div class="table-wrap">
        <table class="data-table" id="top-gainers">
          <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>收盘价</th><th>成交额(亿)</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
    <section class="table-section">
      <h2>跌幅榜 TOP 10</h2>
      <div class="table-wrap">
        <table class="data-table" id="top-losers">
          <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>收盘价</th><th>成交额(亿)</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"><p><a href="../index.html">返回报表列表</a></p></div>
  </footer>

  <script src="../../js/chart.js"></script>
  <script>
    const data = {json.dumps(data, ensure_ascii=False)};
    renderIndexStats(data.indices, 'index-stats');
    renderIndexChart('index-chart', data.indices);
    renderDistributionChart('distribution-chart', data.market_distribution);
    renderStockTable('top-gainers', data.top_gainers, true);
    renderStockTable('top-losers', data.top_losers, false);
  </script>
</body>
</html>
"""


def render_industry_report(data: dict) -> str:
    industries = data.get("industries", [])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data['trade_date']} 板块行业 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        板块行业
      </nav>
      <h1 class="site-title">{data['trade_date']} 板块行业分析</h1>
      <p class="site-subtitle">更新于 {data['updated_at']}</p>
    </div>
  </header>

  <main class="container report-body">
    <section class="chart-section">
      <h2>行业涨跌幅</h2>
      <div id="industry-chart" class="chart-box"></div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"><p><a href="../index.html">返回报表列表</a></p></div>
  </footer>

  <script src="../../js/chart.js"></script>
  <script>
    renderIndustryChart('industry-chart', {json.dumps(industries, ensure_ascii=False)});
  </script>
</body>
</html>
"""


def render_fund_flow_report(data: dict) -> str:
    ff = data.get("fund_flow", {})
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data['trade_date']} 资金流向 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        资金流向
      </nav>
      <h1 class="site-title">{data['trade_date']} 资金流向</h1>
      <p class="site-subtitle">更新于 {data['updated_at']}</p>
    </div>
  </header>

  <main class="container report-body">
    <section class="stats-row">
      <div class="stat-card">
        <div class="name">北向资金净流入</div>
        <div class="value">{ff.get('north_net', 0):.2f} 亿</div>
      </div>
      <div class="stat-card">
        <div class="name">主力资金净流入</div>
        <div class="value">{ff.get('main_net', 0):.2f} 亿</div>
      </div>
      <div class="stat-card">
        <div class="name">散户资金净流入</div>
        <div class="value">{ff.get('retail_net', 0):.2f} 亿</div>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"><p><a href="../index.html">返回报表列表</a></p></div>
  </footer>
</body>
</html>
"""


def render_stock_rank_report(data: dict) -> str:
    gainers_rows = "".join(
        f"<tr><td>{s['code']}</td><td>{s['name']}</td>"
        f"<td class=\"text-up\">+{s['change_pct']:.2f}%</td>"
        f"<td>{s['close']:.2f}</td><td>{s['amount']:.2f}</td></tr>"
        for s in data.get("top_gainers", [])
    )
    losers_rows = "".join(
        f"<tr><td>{s['code']}</td><td>{s['name']}</td>"
        f"<td class=\"text-down\">{s['change_pct']:.2f}%</td>"
        f"<td>{s['close']:.2f}</td><td>{s['amount']:.2f}</td></tr>"
        for s in data.get("top_losers", [])
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data['trade_date']} 个股排行 · A股全景</title>
  <link rel="stylesheet" href="../../css/common.css">
  <link rel="stylesheet" href="../../css/report.css">
</head>
<body>
  <header class="site-header">
    <div class="container">
      <nav class="breadcrumb">
        <a href="../../index.html">首页</a> /
        <a href="../index.html">报表列表</a> /
        个股排行
      </nav>
      <h1 class="site-title">{data['trade_date']} 个股涨跌排行</h1>
      <p class="site-subtitle">更新于 {data['updated_at']}</p>
    </div>
  </header>

  <main class="container report-body">
    <section class="table-section">
      <h2>涨幅榜</h2>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>收盘价</th><th>成交额(亿)</th></tr></thead>
          <tbody>{gainers_rows}</tbody>
        </table>
      </div>
    </section>
    <section class="table-section">
      <h2>跌幅榜</h2>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>代码</th><th>名称</th><th>涨跌幅</th><th>收盘价</th><th>成交额(亿)</th></tr></thead>
          <tbody>{losers_rows}</tbody>
        </table>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container"><p><a href="../index.html">返回报表列表</a></p></div>
  </footer>
</body>
</html>
"""


def update_report_index(data: dict) -> None:
    """更新报表列表页，追加当日报表链接。"""
    index_path = REPORTS_DIR / "index.html"
    if not index_path.exists():
        return

    slug = date_slug(data["trade_date"])
    content = index_path.read_text(encoding="utf-8")

    categories = [
        ("daily", f"daily/{slug}.html", f"{data['trade_date']} 每日行情概览"),
        ("industry", f"industry/{slug}.html", f"{data['trade_date']} 板块行业分析"),
        ("fund_flow", f"fund_flow/{slug}.html", f"{data['trade_date']} 资金流向"),
        ("stock_rank", f"stock_rank/{slug}.html", f"{data['trade_date']} 个股涨跌排行"),
    ]

    for cat, href, title in categories:
        list_pattern = rf'(<ul class="report-list" data-category="{cat}">)(.*?)(</ul>)'
        match = re.search(list_pattern, content, re.DOTALL)
        if not match:
            continue

        inner = match.group(2)
        if href in inner:
            continue

        # 移除 empty-hint
        inner = re.sub(r'<li class="report-item empty-hint">.*?</li>\s*', '', inner, flags=re.DOTALL)

        new_item = f"""
        <li class="report-item" data-name="{slug} {title}">
          <a href="{href}">
            <span class="report-date">{data['trade_date']}</span>
            <span class="report-title">{title}</span>
            <span class="report-tag">{cat}</span>
          </a>
        </li>"""

        new_inner = new_item + inner
        content = content[:match.start(2)] + new_inner + content[match.end(2):]

    index_path.write_text(content, encoding="utf-8")
    print(f"[gen_report] 已更新 {index_path}")


def main() -> None:
    data = load_data()
    slug = date_slug(data["trade_date"])

    reports = {
        REPORTS_DIR / "daily" / f"{slug}.html": render_daily_report(data),
        REPORTS_DIR / "industry" / f"{slug}.html": render_industry_report(data),
        REPORTS_DIR / "fund_flow" / f"{slug}.html": render_fund_flow_report(data),
        REPORTS_DIR / "stock_rank" / f"{slug}.html": render_stock_rank_report(data),
    }

    for path, html in reports.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        print(f"[gen_report] 已生成 {path}")

    update_report_index(data)
    print("[gen_report] 完成")


if __name__ == "__main__":
    main()
