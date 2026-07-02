#!/usr/bin/env python3
"""根据个股 JSON 生成 HTML 分析报表。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STOCK_DATA_DIR = ROOT / "assets" / "data" / "stocks"
WATCHLIST_FILE = ROOT / "assets" / "data" / "watchlist.json"
REPORTS_DIR = ROOT / "reports" / "stock"

import sys
sys.path.insert(0, str(ROOT))
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.watchlist_utils import ensure_watchlist_stocks, get_watchlist_codes

CACHE_META = """  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">"""


def load_stock(code: str) -> dict:
    path = STOCK_DATA_DIR / f"{code}.json"
    if not path.exists():
        raise FileNotFoundError(f"个股数据不存在: {path}，请先运行 python quant_system/main.py stock")
    return json.loads(path.read_text(encoding="utf-8"))


def render_stock_report(data: dict) -> str:
    code = data["code"]
    name = data["name"]
    q = data["quote"]
    live_refresh_ms = CrawlerConfig().live_refresh_sec * 1000
    a = data["analysis"]
    ret = a["returns"]
    ma = a["ma"]
    rng = a["range_60d"]
    factors = data.get("factors") or {}
    quality = data.get("quality") or {}
    predict_path = ROOT / "assets" / "data" / "predictions" / f"{code}.json"
    prediction = {}
    if predict_path.exists():
        prediction = json.loads(predict_path.read_text(encoding="utf-8"))
    if not factors:
        factor_path = ROOT / "assets" / "data" / "factors" / f"{code}.json"
        if factor_path.exists():
            factors = json.loads(factor_path.read_text(encoding="utf-8")).get("factors", {})

    def fac(key, fmt=".2f", suffix=""):
        v = factors.get(key)
        if v is None:
            return "--"
        if isinstance(v, bool):
            return "是" if v else "否"
        if isinstance(v, str):
            return v
        return f"{v:{fmt}}{suffix}"

    def pct(v, signed=True):
        if v is None:
            return "--"
        sign = "+" if v >= 0 and signed else ""
        return f"{sign}{v:.2f}%"

    def ma_badge(w):
        ok = a["ma_signal"].get(f"above_ma{w}", False)
        cls = "text-up" if ok else "text-down"
        label = "站上" if ok else "跌破"
        return f'<span class="{cls}">{label} MA{w}</span>'

    def pred_dir(d):
        return {"up": "偏多 ↑", "down": "偏空 ↓", "neutral": "震荡 →"}.get(d, d or "--")

    def pred_conf(c):
        return {"low": "低", "medium": "中", "high": "高"}.get(c, c or "--")

    risk_flags = ", ".join(prediction.get("risk_flags") or []) or "无"

    primary_signal = data.get("primary_signal") or {}
    if not primary_signal:
        sig_path = ROOT / "assets" / "data" / "signals" / f"{code}.json"
        if sig_path.exists():
            primary_signal = json.loads(sig_path.read_text(encoding="utf-8"))

    def sig_label(s):
        return {"bullish": "偏多 ↑", "bearish": "偏空 ↓", "neutral": "震荡 →"}.get(s, s or "--")

    signal_block = ""
    if primary_signal:
        sig_drivers = "、".join(primary_signal.get("drivers") or []) or "—"
        sig_limits = "、".join(primary_signal.get("limitations") or []) or "—"
        signal_block = f"""
    <section class="live-panel" style="border-color:#0ea5e9;background:rgba(14,165,233,0.08)">
      <div class="live-panel-header">
        <h2 style="margin:0;font-size:1.1rem">初级走势信号 <span class="live-badge">{primary_signal.get('horizon', '5d')}</span></h2>
        <span class="live-status">技术因子倾向 · 未经回测验证</span>
      </div>
      <section class="stats-row">
        <div class="stat-card">
          <div class="name">信号方向</div>
          <div class="value">{sig_label(primary_signal.get('signal'))}</div>
          <div class="change">强度 {primary_signal.get('signal_score', '--')}</div>
        </div>
        <div class="stat-card">
          <div class="name">驱动因子</div>
          <div class="value" style="font-size:0.95rem">{sig_drivers}</div>
          <div class="change">限制: {sig_limits}</div>
        </div>
      </section>
    </section>"""

    pred_block = ""
    if prediction:
        prob = prediction.get("probability")
        prob_s = f"{prob * 100:.1f}%" if prob is not None else "--"
        exp = prediction.get("expected_return")
        exp_s = f"{exp * 100:.2f}%" if exp is not None else "--"
        drivers = "、".join(prediction.get("drivers") or []) or "—"
        pred_block = f"""
    <section class="live-panel" style="border-color:#8b5cf6;background:rgba(139,92,246,0.08)">
      <div class="live-panel-header">
        <h2 style="margin:0;font-size:1.1rem">走势预测 <span class="live-badge">{prediction.get('horizon', '5d')}</span></h2>
        <span class="live-status">{prediction.get('disclaimer', '')}</span>
      </div>
      <section class="stats-row">
        <div class="stat-card">
          <div class="name">{prediction.get('horizon', '5d')} 方向</div>
          <div class="value">{pred_dir(prediction.get('direction'))}</div>
          <div class="change">概率 {prob_s}</div>
        </div>
        <div class="stat-card">
          <div class="name">置信度</div>
          <div class="value">{pred_conf(prediction.get('confidence'))}</div>
          <div class="change">预期收益 {exp_s}</div>
        </div>
        <div class="stat-card">
          <div class="name">回测胜率</div>
          <div class="value">{(prediction.get('evidence') or {}).get('backtest_win_rate', 0) * 100:.1f}%</div>
          <div class="change">样本 {(prediction.get('evidence') or {}).get('sample_count', '--')}</div>
        </div>
        <div class="stat-card">
          <div class="name">驱动 / 风险</div>
          <div class="value" style="font-size:0.95rem">{drivers}</div>
          <div class="change">{risk_flags}</div>
        </div>
      </section>
    </section>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
{CACHE_META}
  <title>{name} ({code}) 个股分析 · A股全景</title>
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
        <a href="../index.html#stock">个股分析</a> /
        {name}
      </nav>
      <h1 class="site-title">{name} <span class="stock-code">{code}</span></h1>
      <p class="site-subtitle">
        交易日 {data['trade_date']} · 更新于 {data['updated_at']} ·
        趋势 <strong>{a['trend']}</strong>
        {(
            f" · 日K滞后至 {data['kline_date']}" if data.get('kline_stale')
            else " · 日K已用实时价补全" if data.get('kline_merged')
            else f" · 日K截至 {data['kline_date']}" if data.get('kline_date') and data.get('kline_date') != data['trade_date']
            else ""
        )}
        {f" · 质量分 {quality['quality_score']} ({quality['status']})" if quality.get('quality_score') is not None else ""}
      </p>
    </div>
  </header>

  <main class="container report-body">
{signal_block}
{pred_block}
    <section class="live-panel" id="live-panel">
      <div class="live-panel-header">
        <h2 style="margin:0;font-size:1.1rem">盘中实时 <span class="live-badge" id="live-badge">LIVE</span></h2>
        <span class="live-status" id="live-status">连接中…</span>
      </div>
      <section class="stats-row">
        <div class="stat-card">
          <div class="name">现价</div>
          <div class="value" id="live-price">--</div>
          <div class="change" id="live-change">--</div>
        </div>
        <div class="stat-card">
          <div class="name">盘中信号</div>
          <div class="value" id="live-signal" style="font-size:1.2rem">--</div>
          <div class="change" id="live-updated">--</div>
        </div>
        <div class="stat-card">
          <div class="name">量比</div>
          <div class="value" id="live-volume-ratio">--</div>
          <div class="change">近20根1分钟均量</div>
        </div>
        <div class="stat-card">
          <div class="name">5分/15分涨跌</div>
          <div class="value" style="font-size:1rem"><span id="live-change-5m">--</span> / <span id="live-change-15m">--</span></div>
          <div class="change">MA5 <span id="live-ma5">--</span> · MA20 <span id="live-ma20">--</span></div>
        </div>
      </section>
      <section class="chart-section" style="margin-bottom:0">
        <h2>1 分钟走势（最近 120 根）</h2>
        <div id="minute-chart" class="chart-box chart-box-sm"></div>
      </section>
    </section>

    <section class="stats-row">
      <div class="stat-card">
        <div class="name">最新价</div>
        <div class="value">{q['close']:.2f}</div>
        <div class="change {'text-up' if q['change_pct'] >= 0 else 'text-down'}">
          {pct(q['change_pct'])} ({'+' if q['change'] >= 0 else ''}{q['change']:.2f})
        </div>
      </div>
      <div class="stat-card">
        <div class="name">成交额</div>
        <div class="value">{q['amount_yi']:.2f} 亿</div>
        <div class="change">换手 {a['turnover']:.2f}%</div>
      </div>
      <div class="stat-card">
        <div class="name">60日区间位置</div>
        <div class="value">{rng['position_pct']:.1f}%</div>
        <div class="change">{rng['low']:.2f} ~ {rng['high']:.2f}</div>
      </div>
      <div class="stat-card">
        <div class="name">均线状态</div>
        <div class="value" style="font-size:1rem">{ma_badge(5)} {ma_badge(20)}</div>
        <div class="change">MA5 {ma['ma5']:.2f} · MA20 {ma['ma20']:.2f}</div>
      </div>
    </section>

    <section class="stats-row">
      <div class="stat-card">
        <div class="name">5日涨跌</div>
        <div class="value {'text-up' if (ret['d5'] or 0) >= 0 else 'text-down'}">{pct(ret['d5'])}</div>
      </div>
      <div class="stat-card">
        <div class="name">20日涨跌</div>
        <div class="value {'text-up' if (ret['d20'] or 0) >= 0 else 'text-down'}">{pct(ret['d20'])}</div>
      </div>
      <div class="stat-card">
        <div class="name">60日涨跌</div>
        <div class="value {'text-up' if (ret['d60'] or 0) >= 0 else 'text-down'}">{pct(ret['d60'])}</div>
      </div>
      <div class="stat-card">
        <div class="name">今开 / 最高 / 最低</div>
        <div class="value" style="font-size:1rem">{q['open']:.2f} / {q['high']:.2f} / {q['low']:.2f}</div>
      </div>
    </section>

    <section class="stats-row">
      <div class="stat-card">
        <div class="name">RSI(14)</div>
        <div class="value">{fac('rsi14')}</div>
        <div class="change">MA20 乖离 {fac('ma20_bias', suffix='%')}</div>
      </div>
      <div class="stat-card">
        <div class="name">MACD</div>
        <div class="value" style="font-size:1rem">{fac('macd', '.4f')} / {fac('macd_signal', '.4f')}</div>
        <div class="change">柱 {fac('macd_hist', '.4f')}</div>
      </div>
      <div class="stat-card">
        <div class="name">20日动量</div>
        <div class="value">{fac('momentum_20', suffix='%')}</div>
        <div class="change">量比(20) {fac('volume_ratio_20')}</div>
      </div>
      <div class="stat-card">
        <div class="name">ATR(14) / 均线</div>
        <div class="value" style="font-size:1rem">{fac('atr14', '.4f')}</div>
        <div class="change">MA交叉 {fac('ma_cross')} · 站上MA20 {fac('above_ma20')}</div>
      </div>
    </section>

    <section class="chart-section">
      <h2>日 K 线（前复权）+ 均线</h2>
      <div id="kline-chart" class="chart-box chart-box-lg"></div>
    </section>

    <section class="chart-section">
      <h2>成交量</h2>
      <div id="volume-chart" class="chart-box chart-box-sm"></div>
    </section>

    <section class="table-section">
      <h2>近 20 个交易日</h2>
      <div class="table-wrap">
        <table class="data-table" id="recent-table">
          <thead>
            <tr>
              <th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th>
              <th>MA5</th><th>MA20</th><th>成交量</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="container">
      <p><a href="../index.html#stock">返回个股列表</a></p>
    </div>
  </footer>

  <script src="../../js/chart.js"></script>
  <script src="../../js/live.js"></script>
  <script>
    const stockData = {json.dumps(data, ensure_ascii=False)};
    const stockCode = "{code}";
    renderStockKlineChart('kline-chart', stockData.kline);
    renderStockVolumeChart('volume-chart', stockData.kline);
    renderStockRecentTable('recent-table', stockData.kline.slice(-20));
    startLiveRefresh(stockCode, {live_refresh_ms});
  </script>
</body>
</html>
"""


def update_report_index(stocks: list[dict]) -> None:
    index_path = ROOT / "reports" / "index.html"
    if not index_path.exists() or not stocks:
        return

    content = index_path.read_text(encoding="utf-8")

    if 'data-category="stock"' not in content:
        stock_section = """
    <section id="stock" class="report-section">
      <h2>个股分析</h2>
      <ul class="report-list" data-category="stock">
        <li class="report-item empty-hint">运行 fetch_stock.py 后自动生成</li>
      </ul>
    </section>
"""
        content = content.replace("</main>", stock_section + "\n  </main>", 1)

        if 'value="stock"' not in content:
            content = content.replace(
                '<option value="stock_rank">个股排行</option>',
                '<option value="stock_rank">个股排行</option>\n        <option value="stock">个股分析</option>',
            )

    list_pattern = r'(<ul class="report-list" data-category="stock">)(.*?)(</ul>)'
    match = re.search(list_pattern, content, re.DOTALL)
    if not match:
        return

    items = []
    for s in stocks:
        code = s["code"]
        name = s["name"]
        href = f"stock/{code}.html"
        items.append(f"""
        <li class="report-item" data-name="{code} {name} 个股分析">
          <a href="{href}">
            <span class="report-date">{s.get('trade_date', '')}</span>
            <span class="report-title">{name} ({code}) · {s.get('trend', '')}</span>
            <span class="report-tag">stock</span>
          </a>
        </li>""")

    new_inner = "".join(items)
    content = content[:match.start(2)] + new_inner + content[match.end(2):]
    index_path.write_text(content, encoding="utf-8")
    print(f"[gen_stock_report] 已更新 {index_path}")


def load_watchlist_codes() -> list[str]:
    if not WATCHLIST_FILE.exists():
        return []
    data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return [str(s["code"]) for s in data.get("stocks", [])]


def cleanup_stale_stock_files(active_codes: list[str]) -> None:
    """删除不在 watchlist 中的过期 JSON / HTML 报表。"""
    active = set(active_codes)
    for path in STOCK_DATA_DIR.glob("*.json"):
        if path.stem == "index":
            continue
        if path.stem not in active:
            path.unlink()
            print(f"[gen_stock_report] 已删除过期数据 {path.name}")
    for path in REPORTS_DIR.glob("*.html"):
        if path.stem not in active:
            path.unlink()
            print(f"[gen_stock_report] 已删除过期报表 {path.name}")


def main() -> None:
    ensure_watchlist_stocks()
    codes = get_watchlist_codes()
    if not codes:
        index_file = STOCK_DATA_DIR / "index.json"
        if index_file.exists():
            index = json.loads(index_file.read_text(encoding="utf-8"))
            codes = [s["code"] for s in index.get("stocks", [])]
        else:
            codes = [p.stem for p in STOCK_DATA_DIR.glob("*.json") if p.stem != "index"]

    if not codes:
        print("[gen_stock_report] 无个股数据，请先运行 fetch_stock.py")
        return

    cleanup_stale_stock_files(codes)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    generated = []

    for code in codes:
        try:
            data = load_stock(code)
        except FileNotFoundError as e:
            print(f"[gen_stock_report] 跳过 {code}: {e}")
            continue
        out = REPORTS_DIR / f"{code}.html"
        out.write_text(render_stock_report(data), encoding="utf-8")
        print(f"[gen_stock_report] 已生成 {out}")
        generated.append({
            "code": code,
            "name": data["name"],
            "trade_date": data["trade_date"],
            "trend": data["analysis"]["trend"],
        })

    update_report_index(generated)
    print("[gen_stock_report] 完成")


if __name__ == "__main__":
    main()
