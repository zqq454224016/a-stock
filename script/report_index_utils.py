#!/usr/bin/env python3
"""同步 reports/index.html 中的 MVP 汇总入口（Agent / 因子 / 预测等）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_system.presentation.report_base import data_path, read_json, read_text, report_path, write_html

INDEX_PATH = report_path("index.html")
DATA_DIR = data_path()


def _read_json(path: Path) -> dict | list | None:
    return read_json(path, None)


def _hub_item(date: str, title: str, href: str, tag: str, name: str) -> str:
    tag_label = {
        "agent": "智能分析",
        "factors": "多因子",
        "predict": "走势预测",
        "replay": "历史推演",
        "review": "后验复盘",
        "selector": "上涨候选",
        "decision": "操作建议",
        "impact": "实际影响",
        "attribution": "每日归因",
        "trading": "模拟交易",
        "portfolio": "组合管理",
        "factor_eval": "因子评估",
        "recommendation": "多周期推荐",
        "framework": "模块框架",
        "console": "统一控制台",
        "monitoring": "监控告警",
        "planning": "v3路线",
        "enhance": "数据增强",
        "backtest": "策略回测",
    }.get(tag, tag)
    return f"""
        <li class="report-item" data-name="{name}">
          <a href="{href}">
            <span class="report-date">{date}</span>
            <span class="report-title">{title}</span>
            <span class="report-tag">{tag_label}</span>
          </a>
        </li>"""


def _section(section_id: str, title: str, category: str, items_html: str) -> str:
    body = items_html.strip() or '<li class="report-item empty-hint">暂无数据</li>'
    return f"""
    <section id="{section_id}" class="report-section">
      <h2>{title}</h2>
      <ul class="report-list" data-category="{category}">
{body}
      </ul>
    </section>"""


def _ensure_filter_option(content: str, value: str, label: str) -> str:
    if f'value="{value}"' in content:
        return content
    return content.replace(
        '<option value="all">全部分类</option>',
        f'<option value="all">全部分类</option>\n        <option value="{value}">{label}</option>',
        1,
    )


def _upsert_section(content: str, section_id: str, section_html: str) -> str:
    pattern = rf'<section id="{section_id}" class="report-section">.*?</section>'
    if re.search(pattern, content, re.DOTALL):
        return re.sub(pattern, section_html.strip(), content, count=1, flags=re.DOTALL)
    return content.replace("</main>", section_html + "\n  </main>", 1)


def build_agent_items() -> str:
    items = [
        _hub_item("汇总", "Agent 统一看板", "agent/index.html", "agent", "Agent 统一看板"),
    ]
    index = _read_json(DATA_DIR / "agent" / "index.json")
    rows = (index or {}).get("reports", []) if isinstance(index, dict) else []
    if not rows:
        for path in sorted((DATA_DIR / "agent").glob("*.json")):
            if path.stem == "index":
                continue
            rows.append(read_json(path, {}))
    for row in rows:
        code = row.get("code", "")
        name = row.get("name") or code
        summary = row.get("summary", "")
        items.append(_hub_item(
            row.get("trade_date", "—"),
            f"{name} ({code}) · {summary}",
            f"agent/{code}.html",
            "agent",
            f"{code} {name} Agent",
        ))
    return "".join(items)


def build_factor_items() -> str:
    if not report_path("factors", "index.html").exists():
        return ""
    return _hub_item("汇总", "多因子排名", "factors/index.html", "factors", "多因子排名")


def build_factor_eval_items() -> str:
    if not report_path("factor_eval", "index.html").exists():
        return ""
    return _hub_item("汇总", "因子有效性评估", "factor_eval/index.html", "factor_eval", "因子有效性评估")


def build_recommendation_items() -> str:
    if not report_path("recommendations", "index.html").exists():
        return ""
    return _hub_item("汇总", "短中长线推荐", "recommendations/index.html", "recommendation", "短中长线推荐")


def build_framework_items() -> str:
    if not report_path("framework", "index.html").exists():
        return ""
    return _hub_item("汇总", "模块化算法框架", "framework/index.html", "framework", "模块化算法框架")


def build_console_items() -> str:
    if not report_path("console", "index.html").exists():
        return ""
    return _hub_item("汇总", "统一 Web 控制台", "console/index.html", "console", "统一 Web 控制台")


def build_monitoring_items() -> str:
    if not report_path("monitoring", "index.html").exists():
        return ""
    return _hub_item("汇总", "监控告警与数据血缘", "monitoring/index.html", "monitoring", "监控告警与数据血缘")


def build_planning_items() -> str:
    if not report_path("planning", "v3.html").exists():
        return ""
    return _hub_item("汇总", "v3 稳定化与扩展路线", "planning/v3.html", "planning", "v3 稳定化与扩展路线")


def build_predict_items() -> str:
    if not report_path("predict", "index.html").exists():
        return ""
    return _hub_item("汇总", "走势预测汇总", "predict/index.html", "predict", "走势预测汇总")


def build_replay_items() -> str:
    if not report_path("replay", "index.html").exists():
        return ""
    return _hub_item("汇总", "十日前滚动推演", "replay/index.html", "replay", "十日前滚动推演")


def build_review_items() -> str:
    if not report_path("review", "index.html").exists():
        return ""
    return _hub_item("汇总", "后验复盘", "review/index.html", "review", "后验复盘")


def build_decision_items() -> str:
    if not report_path("decision", "index.html").exists():
        return ""
    return _hub_item("汇总", "单股操作建议", "decision/index.html", "decision", "单股操作建议")


def build_selector_items() -> str:
    if not report_path("selector", "index.html").exists():
        return ""
    return _hub_item("汇总", "上涨候选池", "selector/index.html", "selector", "上涨候选池")


def build_impact_items() -> str:
    if not report_path("impact", "index.html").exists():
        return ""
    return _hub_item("汇总", "实际影响数据", "impact/index.html", "impact", "实际影响数据")


def build_attribution_items() -> str:
    if not report_path("attribution", "index.html").exists():
        return ""
    return _hub_item("汇总", "每日涨跌归因", "attribution/index.html", "attribution", "每日涨跌归因")


def build_trading_items() -> str:
    if not report_path("trading", "index.html").exists():
        return ""
    return _hub_item("汇总", "模拟交易看板", "trading/index.html", "trading", "模拟交易看板")


def build_portfolio_items() -> str:
    if not report_path("portfolio", "index.html").exists():
        return ""
    return _hub_item("汇总", "组合管理", "portfolio/index.html", "portfolio", "组合管理")


def build_enhance_items() -> str:
    if not report_path("enhance", "index.html").exists():
        return ""
    return _hub_item("汇总", "数据增强摘要", "enhance/index.html", "enhance", "数据增强摘要")


def build_backtest_items() -> str:
    items: list[str] = []
    index = _read_json(DATA_DIR / "backtest" / "index.json")
    rows = (index or {}).get("results", []) if isinstance(index, dict) else []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        code = row.get("code", "")
        strategy = row.get("strategy", "ma_cross")
        key = (code, strategy)
        if key in seen:
            continue
        seen.add(key)
        path = report_path("backtest", f"{code}_{strategy}.html")
        if not path.exists():
            continue
        items.append(_hub_item(
            strategy,
            f"{code} · {strategy}",
            f"backtest/{code}_{strategy}.html",
            "backtest",
            f"{code} {strategy} 回测",
        ))
    if not items:
        for path in sorted(report_path("backtest").glob("*_*.html")):
            stem = path.stem
            if "_" not in stem:
                continue
            code, strategy = stem.rsplit("_", 1)
            items.append(_hub_item(
                strategy,
                f"{code} · {strategy}",
                f"backtest/{path.name}",
                "backtest",
                f"{code} {strategy} 回测",
            ))
    return "".join(items)


def sync_report_index_hubs() -> bool:
    """将 Agent / 因子 / 预测 / 增强 / 回测 入口写入 reports/index.html。"""
    if not INDEX_PATH.exists():
        print(f"[report_index] 跳过：{INDEX_PATH} 不存在")
        return False

    content = read_text(INDEX_PATH)

    hubs = [
        ("console", "console", "统一控制台", build_console_items()),
        ("monitoring", "monitoring", "监控告警", build_monitoring_items()),
        ("planning", "planning", "v3路线", build_planning_items()),
        ("agent", "agent", "智能分析", build_agent_items()),
        ("factors", "factors", "多因子排名", build_factor_items()),
        ("factor-eval", "factor_eval", "因子有效性", build_factor_eval_items()),
        ("recommendations", "recommendation", "多周期推荐", build_recommendation_items()),
        ("framework", "framework", "模块框架", build_framework_items()),
        ("predict", "predict", "走势预测", build_predict_items()),
        ("replay", "replay", "历史推演", build_replay_items()),
        ("review", "review", "后验复盘", build_review_items()),
        ("selector", "selector", "上涨候选", build_selector_items()),
        ("decision", "decision", "操作建议", build_decision_items()),
        ("impact", "impact", "实际影响", build_impact_items()),
        ("attribution", "attribution", "每日归因", build_attribution_items()),
        ("trading", "trading", "模拟交易", build_trading_items()),
        ("portfolio", "portfolio", "组合管理", build_portfolio_items()),
        ("enhance", "enhance", "数据增强", build_enhance_items()),
        ("backtest", "backtest", "策略回测", build_backtest_items()),
    ]

    for section_id, category, title, items_html in hubs:
        if not items_html:
            continue
        content = _ensure_filter_option(content, category, title)
        content = _upsert_section(content, section_id, _section(section_id, title, category, items_html))

    content = re.sub(r"^[ \t]+$", "", content, flags=re.MULTILINE)
    write_html(INDEX_PATH, content)
    print(f"[report_index] 已同步 MVP 入口 → {INDEX_PATH}")
    return True


if __name__ == "__main__":
    sync_report_index_hubs()
