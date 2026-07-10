"""每日涨跌归因构建器。"""

from __future__ import annotations

from statistics import mean
from typing import Any

from quant_system.utils.time_utils import now_str

DAILY_ATTRIBUTION_VERSION = "1.0.0"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return round((a - b) / b * 100, 2)


def _direction(change_pct: float) -> str:
    if change_pct > 0.2:
        return "up"
    if change_pct < -0.2:
        return "down"
    return "flat"


def _cause(category: str, label: str, effect: str, evidence: str, *, source: str, weight: float = 1.0) -> dict[str, Any]:
    return {
        "category": category,
        "label": label,
        "effect": effect,
        "evidence": evidence,
        "source": source,
        "weight": round(weight, 2),
    }


def _sorted_kline(stock: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in stock.get("kline") or [] if row.get("date")]
    return sorted(rows, key=lambda row: str(row.get("date")))


def _row_fact(rows: list[dict[str, Any]], idx: int) -> dict[str, Any]:
    pos = idx if idx >= 0 else len(rows) + idx
    row = rows[pos]
    prev = rows[pos - 1] if pos > 0 else {}
    close = _f(row.get("close"))
    prev_close = _f(prev.get("close"), close)
    open_price = _f(row.get("open"), close)
    high = _f(row.get("high"), close)
    low = _f(row.get("low"), close)
    volume = _f(row.get("volume"))
    lookback = rows[max(0, pos - 20):pos]
    avg_volume = mean([_f(x.get("volume")) for x in lookback if _f(x.get("volume")) > 0]) if lookback else 0.0
    volume_ratio = round(volume / avg_volume, 2) if avg_volume > 0 and volume > 0 else 0.0
    return {
        "date": row.get("date"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "prev_close": prev_close,
        "return_pct": _pct(close, prev_close),
        "intraday_pct": _pct(close, open_price),
        "amplitude_pct": _pct(high, low),
        "volume": volume,
        "volume_ratio_20": volume_ratio,
        "ma5": _f(row.get("ma5")),
        "ma10": _f(row.get("ma10")),
        "ma20": _f(row.get("ma20")),
        "ma60": _f(row.get("ma60")),
        "direction": _direction(_pct(close, prev_close)),
    }


def _market_causes(market: dict[str, Any] | None, day_direction: str) -> list[dict[str, Any]]:
    if not market:
        return []
    causes: list[dict[str, Any]] = []
    indices = market.get("indices") or []
    weak = [x for x in indices if _f(x.get("change_pct")) <= -1]
    strong = [x for x in indices if _f(x.get("change_pct")) >= 1]
    if weak:
        names = "、".join(str(x.get("name")) for x in weak[:3])
        causes.append(_cause("market", "大盘走弱", "bearish", f"{names} 跌幅超过1%", source="latest.indices", weight=1.1))
    if strong and day_direction == "up":
        names = "、".join(str(x.get("name")) for x in strong[:3])
        causes.append(_cause("market", "大盘或参考指数走强", "bullish", f"{names} 涨幅超过1%", source="latest.indices", weight=0.8))
    fund = market.get("fund_flow") or {}
    main_net = _f(fund.get("main_net"))
    if main_net <= -100:
        causes.append(_cause("fund_flow", "市场主力资金净流出", "bearish", f"主力净流出 {main_net:.2f} 亿", source="latest.fund_flow", weight=1.0))
    elif main_net >= 100:
        causes.append(_cause("fund_flow", "市场主力资金净流入", "bullish", f"主力净流入 {main_net:.2f} 亿", source="latest.fund_flow", weight=1.0))
    dist = market.get("market_distribution") or []
    down_count = sum(int(_f(x.get("count"))) for x in dist if "跌" in str(x.get("label")))
    up_count = sum(int(_f(x.get("count"))) for x in dist if "涨" in str(x.get("label")))
    if down_count > up_count * 1.5 and down_count > 0:
        causes.append(_cause("market_breadth", "市场宽度偏弱", "bearish", f"上涨 {up_count} 家，下跌 {down_count} 家", source="latest.market_distribution", weight=0.9))
    elif up_count > down_count * 1.5 and up_count > 0:
        causes.append(_cause("market_breadth", "市场宽度偏强", "bullish", f"上涨 {up_count} 家，下跌 {down_count} 家", source="latest.market_distribution", weight=0.9))
    return causes


def _technical_causes(fact: dict[str, Any], previous_fact: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    causes: list[dict[str, Any]] = []
    ret = _f(fact.get("return_pct"))
    close = _f(fact.get("close"))
    ma5 = _f(fact.get("ma5"))
    ma20 = _f(fact.get("ma20"))
    volume_ratio = _f(fact.get("volume_ratio_20"))
    intraday = _f(fact.get("intraday_pct"))
    amplitude = _f(fact.get("amplitude_pct"))
    if ret >= 3:
        causes.append(_cause("price_action", "单日涨幅较强", "bullish", f"收盘涨幅 {ret:.2f}%", source="stock.kline", weight=1.1))
    elif ret <= -3:
        causes.append(_cause("price_action", "单日跌幅较深", "bearish", f"收盘跌幅 {ret:.2f}%", source="stock.kline", weight=1.1))
    if close > ma20 > 0:
        causes.append(_cause("trend", "收盘站上 MA20", "bullish", f"收盘 {close:.2f}，MA20 {ma20:.2f}", source="stock.kline", weight=0.9))
    elif ma20 > 0 and close < ma20:
        causes.append(_cause("trend", "收盘跌破 MA20", "bearish", f"收盘 {close:.2f}，MA20 {ma20:.2f}", source="stock.kline", weight=1.0))
    if ma5 > 0 and close < ma5:
        causes.append(_cause("short_trend", "收盘低于 MA5", "bearish", f"收盘 {close:.2f}，MA5 {ma5:.2f}", source="stock.kline", weight=0.8))
    if volume_ratio >= 1.3 and ret > 0:
        causes.append(_cause("volume", "放量上涨", "bullish", f"20日量比 {volume_ratio:.2f}", source="stock.kline", weight=1.0))
    elif volume_ratio >= 1.3 and ret < 0:
        causes.append(_cause("volume", "放量下跌", "bearish", f"20日量比 {volume_ratio:.2f}", source="stock.kline", weight=1.1))
    elif volume_ratio == 0:
        causes.append(_cause("data_quality", "成交量缺失或为零", "neutral", "当日成交量不可用，资金归因降权", source="stock.kline", weight=0.3))
    if intraday <= -4 and amplitude >= 8:
        causes.append(_cause("intraday", "冲高回落或日内承接弱", "bearish", f"日内涨跌 {intraday:.2f}%，振幅 {amplitude:.2f}%", source="stock.kline", weight=1.0))
    if previous_fact:
        prev_close = _f(previous_fact.get("close"))
        if ret < 0 and prev_close > 0 and close < prev_close:
            causes.append(_cause("reversal", "回吐前一交易日收盘", "bearish", f"收盘 {close:.2f} 低于前日 {prev_close:.2f}", source="stock.kline", weight=1.0))
    return causes


def _impact_causes(impact: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not impact:
        return []
    causes: list[dict[str, Any]] = []
    for event in (impact.get("events") or [])[:5]:
        direction = event.get("impact_direction")
        effect = "bullish" if direction == "positive" else "bearish" if direction == "negative" else "neutral"
        title = event.get("title") or event.get("event_type") or "事件影响"
        evidence = "；".join(str(x) for x in (event.get("evidence") or [])[:2]) or f"影响分 {event.get('impact_score')}"
        causes.append(_cause("event", str(title), effect, evidence, source=f"impact.{event.get('event_type') or 'event'}", weight=1.0))
    if not causes and impact.get("impact_direction") in ("positive", "negative"):
        effect = "bullish" if impact.get("impact_direction") == "positive" else "bearish"
        causes.append(_cause("event", "综合事件影响", effect, f"影响分 {impact.get('impact_score')}", source="impact.summary", weight=0.7))
    return causes


def _replay_causes(replay: dict[str, Any] | None, target_date: str) -> list[dict[str, Any]]:
    if not replay:
        return []
    for step in replay.get("steps") or []:
        if step.get("target_date") != target_date:
            continue
        root = step.get("root_cause") or {}
        out = []
        for item in (root.get("actual_root_causes") or [])[:4]:
            out.append(_cause(
                item.get("category") or "replay",
                item.get("label") or "历史推演根因",
                item.get("effect") or "neutral",
                item.get("evidence") or "",
                source=f"replay.{item.get('source') or 'root_cause'}",
                weight=0.8,
            ))
        return out
    return []


def _score(causes: list[dict[str, Any]]) -> dict[str, float]:
    score = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    for cause in causes:
        effect = cause.get("effect") or "neutral"
        score[effect] = score.get(effect, 0.0) + _f(cause.get("weight"), 1.0)
    return {k: round(v, 2) for k, v in score.items()}


def _dominant(causes: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    target = "bullish" if direction == "up" else "bearish" if direction == "down" else "neutral"
    primary = [c for c in causes if c.get("effect") == target]
    fallback = [c for c in causes if c.get("effect") != target]
    return sorted(primary, key=lambda x: _f(x.get("weight")), reverse=True)[:4] or fallback[:3]


def _day_attribution(
    label: str,
    fact: dict[str, Any],
    *,
    previous_fact: dict[str, Any] | None,
    market: dict[str, Any] | None,
    impact: dict[str, Any] | None,
    replay: dict[str, Any] | None,
) -> dict[str, Any]:
    direction = fact.get("direction") or "flat"
    causes = (
        _technical_causes(fact, previous_fact)
        + _market_causes(market, str(direction))
        + _impact_causes(impact)
        + _replay_causes(replay, str(fact.get("date")))
    )
    scores = _score(causes)
    if direction == "up":
        conclusion = "上涨主要由量价/趋势强化、市场或事件正向因素共同解释"
    elif direction == "down":
        conclusion = "下跌主要由技术走弱、资金/大盘压力或事件风险共同解释"
    else:
        conclusion = "涨跌幅较小，暂按震荡处理"
    return {
        "label": label,
        "date": fact.get("date"),
        "fact": fact,
        "direction": direction,
        "cause_scores": scores,
        "dominant_causes": _dominant(causes, str(direction)),
        "all_causes": causes,
        "conclusion": conclusion,
    }


def _logic_review(yesterday: dict[str, Any], today: dict[str, Any]) -> dict[str, Any]:
    y_fact = yesterday.get("fact") or {}
    t_fact = today.get("fact") or {}
    broken_reasons: list[str] = []
    if yesterday.get("direction") == "up" and today.get("direction") == "down":
        broken_reasons.append("昨日上涨后今日转跌，短线延续性不足")
    if _f(t_fact.get("close")) < _f(y_fact.get("close")):
        broken_reasons.append("今日收盘低于昨日收盘，昨日上涨被回吐")
    if _f(t_fact.get("ma20")) > 0 and _f(t_fact.get("close")) < _f(t_fact.get("ma20")):
        broken_reasons.append("今日收盘低于 MA20，中期趋势支撑转弱")
    if any(c.get("label") in ("放量下跌", "冲高回落或日内承接弱") for c in today.get("all_causes") or []):
        broken_reasons.append("今日量价或日内结构显示承接不足")
    support = min(_f(y_fact.get("low")), _f(t_fact.get("low")))
    resistance = max(_f(y_fact.get("high")), _f(t_fact.get("high")))
    return {
        "logic_broken": bool(broken_reasons),
        "broken_reasons": broken_reasons,
        "next_watch": {
            "recover_price": round(max(_f(y_fact.get("close")), _f(t_fact.get("ma5"))), 2),
            "risk_price": round(support, 2),
            "pressure_price": round(resistance, 2),
            "note": "重新站上恢复价且资金/成交同步改善，才视为上涨逻辑修复；跌破风险价则昨日上涨确认失败。",
        },
    }


def build_daily_attribution_payload(
    code: str,
    name: str,
    stock: dict[str, Any],
    *,
    market: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _sorted_kline(stock)
    if len(rows) < 3:
        return {
            "code": code,
            "name": name,
            "daily_attribution_version": DAILY_ATTRIBUTION_VERSION,
            "status": "insufficient_data",
            "items": [],
            "limitations": ["requires_at_least_3_kline_rows"],
            "updated_at": now_str(),
        }
    prev_fact = _row_fact(rows, -3)
    yesterday_fact = _row_fact(rows, -2)
    today_fact = _row_fact(rows, -1)
    yesterday = _day_attribution(
        "昨日",
        yesterday_fact,
        previous_fact=prev_fact,
        market=market,
        impact=impact,
        replay=replay,
    )
    today = _day_attribution(
        "今日",
        today_fact,
        previous_fact=yesterday_fact,
        market=market,
        impact=impact,
        replay=replay,
    )
    pattern = "yesterday_up_today_down" if yesterday["direction"] == "up" and today["direction"] == "down" else f"{yesterday['direction']}_then_{today['direction']}"
    logic = _logic_review(yesterday, today)
    limitations = []
    if market and market.get("degraded"):
        limitations.append("market_data_degraded")
    if _f(today_fact.get("volume")) == 0:
        limitations.append("today_volume_missing_or_zero")
    if not impact:
        limitations.append("impact_missing")
    if not replay:
        limitations.append("replay_missing")
    return {
        "code": code,
        "name": name,
        "daily_attribution_version": DAILY_ATTRIBUTION_VERSION,
        "status": "ok",
        "trade_date": today_fact.get("date"),
        "previous_trade_date": yesterday_fact.get("date"),
        "pattern": pattern,
        "items": [yesterday, today],
        "logic_review": logic,
        "summary": {
            "yesterday_return_pct": yesterday_fact.get("return_pct"),
            "today_return_pct": today_fact.get("return_pct"),
            "logic_broken": logic.get("logic_broken"),
            "primary_today_causes": [x.get("label") for x in today.get("dominant_causes") or []],
        },
        "limitations": limitations,
        "updated_at": now_str(),
    }
