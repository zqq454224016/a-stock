"""报表与日志中的英文标签中文化。"""

from __future__ import annotations

LIMITATION_LABELS: dict[str, str] = {
    "partial_source_failure": "部分数据源失败",
    "valuation_missing": "估值数据缺失",
    "northbound_missing": "北向数据缺失",
    "dividend_missing": "分红数据缺失",
    "bulk_spot_skipped": "已跳过全市场行情",
    "bulk_spot_failed": "全市场行情失败",
    "spot_watchlist_only": "仅自选股行情",
    "spot_stock_cache": "使用个股缓存行情",
    "spot_unavailable": "行情不可用",
    "market_fetch_failed": "大盘采集失败",
    "indices_unavailable": "指数数据不可用",
    "industries_unavailable": "行业数据不可用",
    "not_q2_report_period": "不是二季度报告期",
    "uses_company_reason_text": "仅使用公司原因描述",
    "requires_q2_official_report_or_forecast": "需要补充二季度正式报告或业绩预告",
    "impact_review_missing": "缺少实际影响后验复盘",
    "impact_review_requires_future_kline": "实际影响复盘需要信号日之后的K线",
    "review_requires_future_kline_after_signal_date": "复盘需要信号日之后的K线",
    "watch_action_hit_rule_uses_abs_return_below_1pct": "观望动作以小幅波动作为命中规则",
}

VERDICT_LABELS: dict[str, str] = {
    "positive": "偏多",
    "negative": "偏空",
    "neutral": "中性",
    "ok": "正常",
    "weak": "偏弱",
    "mixed": "分化",
    "aligned": "一致",
    "divergent": "背离",
    "partial": "部分一致",
    "bullish": "偏多",
    "bearish": "偏空",
}

DIRECTION_LABELS: dict[str, str] = {
    "up": "上涨",
    "down": "下跌",
    "neutral": "震荡",
    "positive": "正面",
    "negative": "负面",
}

STATUS_LABELS: dict[str, str] = {
    "pass": "通过",
    "warn": "警告",
    "fail": "失败",
    "ok": "正常",
    "candidate": "候选",
    "rejected": "淘汰",
    "aligned": "一致",
    "divergent": "背离",
    "partial": "部分一致",
}

SOURCE_FAIL_LABELS: dict[str, str] = {
    "dividend": "分红",
    "lockup": "解禁",
    "northbound": "北向持股",
    "margin": "两融",
    "margin_sse": "沪市两融",
    "margin_szse": "深市两融",
    "earnings_forecast": "业绩预告",
    "valuation_em": "东财估值",
    "valuation_baidu_pe": "百度市盈率",
    "valuation_baidu_pb": "百度市净率",
    "individual_info": "个股资料",
}

STRATEGY_LABELS: dict[str, str] = {
    "ma_cross": "均线金叉",
    "multi_factor": "多因子",
}


def translate_label(value: str | None, mapping: dict[str, str]) -> str:
    if not value:
        return "—"
    return mapping.get(value, value)


def translate_limitations(items: list[str] | None) -> str:
    if not items:
        return "—"
    return "、".join(translate_label(x, LIMITATION_LABELS) for x in items)


def translate_verdict(value: str | None) -> str:
    return translate_label(value, VERDICT_LABELS)


def translate_direction(value: str | None) -> str:
    return translate_label(value, DIRECTION_LABELS)


def translate_status(value: str | None) -> str:
    return translate_label(value, STATUS_LABELS)


def translate_source_fail(label: str | None) -> str:
    if not label:
        return "未知"
    if label in SOURCE_FAIL_LABELS:
        return SOURCE_FAIL_LABELS[label]
    if label.startswith("earnings_forecast"):
        return "业绩预告"
    if label.startswith("margin_"):
        return SOURCE_FAIL_LABELS.get(label, "两融")
    return label


def humanize_fetch_error(err: Exception | str) -> str:
    msg = str(err)
    lower = msg.lower()
    if "no tables found" in lower:
        return "页面无数据"
    if "nonetype" in lower and "subscriptable" in lower:
        return "接口返回为空"
    if "length mismatch" in lower:
        return "数据格式不匹配"
    if "proxy" in lower or "remote end closed" in lower:
        return "网络/代理异常"
    if "max retries exceeded" in lower:
        return "请求超时"
    if "connection" in lower and ("refused" in lower or "reset" in lower):
        return "连接失败"
    return msg[:60] + ("…" if len(msg) > 60 else "")
