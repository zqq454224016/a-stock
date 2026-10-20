"""构建短线、中线和长线推荐。"""

from __future__ import annotations

from typing import Any

from quant_system.recommendation.miss_audit import build_miss_audit
from quant_system.strategy.regime_router import apply_evidence as apply_route_evidence
from quant_system.strategy.regime_router import route as route_market_regime
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

RECOMMENDATION_VERSION = "2.3.0"
AGGRESSIVE_LANES = ("momentum_breakout", "trend_pullback", "sector_leader")
PERIODS = {
    "short": {"label": "每日筛选推荐", "horizon": "下一交易日", "threshold": 100.0},
    "aggressive": {"label": "激进板筛选推荐", "horizon": "1-5个交易日", "threshold": 100.0},
    "tail_sector": {"label": "尾盘板块T+1观察", "horizon": "今日尾盘→下一交易日", "threshold": 100.0},
}

# 正式推荐刻意不追当日大涨；研究晋级信号是先验 T+1，不对齐“已涨完”的票。
ANTI_CHASE_POLICY = {
    "weak_change_band": (3.0, 5.0),
    "strong_change_band": (4.0, 6.0),
    "aggressive_change_band": (4.0, 9.5),
    "rationale": "当日涨幅已脱离温和带的票，属于事后追涨样本，不进入正式推荐",
}


def _is_intraday_blocker(text: str) -> bool:
    return any(
        token in text
        for token in ("分时", "尾盘脉冲", "尾盘无跳水", "站稳分时均价")
    )


def _classify_exclusion(
    blockers: list[str],
    *,
    values: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把硬拒绝拆成设计类 / 结构类 / 管线类，便于对抗漏检审计。"""
    values = values or {}
    limits = limits or {}
    classes: list[str] = []
    change = values.get("change_pct")
    change_band = limits.get("change")
    change_low = change_high = None
    if isinstance(change_band, (list, tuple)) and len(change_band) >= 2:
        try:
            change_low, change_high = float(change_band[0]), float(change_band[1])
        except (TypeError, ValueError):
            change_low = change_high = None
    try:
        change_num = float(change) if change is not None else None
    except (TypeError, ValueError):
        change_num = None

    for item in blockers:
        if "分时数据缺失" in item:
            classes.append("intraday_missing")
        elif _is_intraday_blocker(item):
            classes.append("intraday_fail")
        elif "涨幅" in item:
            if change_num is not None and change_high is not None and change_num >= change_high:
                classes.append("anti_chase_change_band")
            elif change_num is not None and change_low is not None and change_num <= change_low:
                classes.append("under_momentum_change_band")
            else:
                classes.append("change_band")
        elif "流通市值" in item:
            classes.append("size_band")
        elif "换手" in item or "量比" in item:
            classes.append("liquidity_band")
        elif "均线" in item or "站稳" in item:
            classes.append("structure_ma")
        elif "放量" in item or "成交量" in item:
            classes.append("volume_shape")
        elif "偏强市场" in item or "情绪" in item:
            classes.append("market_gate")
        elif "突破" in item or "高点" in item:
            classes.append("breakout")
        elif "相对大盘" in item or "强于大盘" in item:
            classes.append("relative_strength")
        else:
            classes.append("other")
    numerical = [item for item in blockers if not _is_intraday_blocker(item)]
    intraday = [item for item in blockers if _is_intraday_blocker(item)]
    return {
        "classes": list(dict.fromkeys(classes)),
        "numerical_blockers": numerical,
        "intraday_blockers": intraday,
        "numerical_passed": not numerical,
        "design_anti_chase": "anti_chase_change_band" in classes,
    }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _market_context(market: dict[str, Any]) -> dict[str, Any]:
    indices = market.get("indices") or []
    normal = [x for x in indices if x.get("name") != "科创50参考"]
    avg_change = sum(_f(x.get("change_pct")) for x in normal) / len(normal) if normal else 0.0
    main_net = _f((market.get("fund_flow") or {}).get("main_net"))
    if avg_change >= 0.5 and main_net >= 0:
        regime, adjustment = "偏强", 4.0
    elif avg_change <= -0.8 or main_net < -100:
        regime, adjustment = "偏弱", -5.0
    else:
        regime, adjustment = "震荡", 0.0
    sentiment = _market_sentiment(market, avg_change, main_net)
    sector = _sector_context(market)
    return {
        "trade_date": market.get("trade_date"),
        "context_dates": market.get("context_dates") or {},
        "regime": regime,
        "index_avg_change_pct": round(avg_change, 2),
        "main_net_yi": main_net,
        "score_adjustment": adjustment,
        "degraded": bool(market.get("degraded")),
        "limitations": market.get("limitations") or [],
        "sentiment": sentiment,
        "sector_market": sector,
        "analysis_points": {
            "market_sentiment": {
                "used_in_scoring": True,
                "adjustment": adjustment,
                "source": "full_market_breadth+indices+fund_flow",
            },
            "sector_market": {
                "used_in_scoring": False,
                "reason": "板块行情已进入上下文；只有取得可核验的个股行业映射后才允许个股加减分",
            },
        },
    }


def _sector_context(market: dict[str, Any]) -> dict[str, Any]:
    raw = market.get("sector_market") or market.get("industries") or []
    rows = raw.get("rows") or [] if isinstance(raw, dict) else raw
    scope = raw.get("scope") if isinstance(raw, dict) else "full"
    normalized = [
        {"name": str(row.get("name") or ""), "change_pct": round(_f(row.get("change_pct")), 2)}
        for row in rows if row.get("name")
    ]
    normalized.sort(key=lambda row: row["change_pct"], reverse=True)
    positive = sum(1 for row in normalized if row["change_pct"] > 0)
    negative = sum(1 for row in normalized if row["change_pct"] < 0)
    total = positive + negative
    breadth = positive / total if total else None
    complete = scope == "full" and len(normalized) >= 10
    return {
        "status": "valid" if complete else "degraded",
        "scope": scope,
        "sample_count": len(normalized),
        "advance_ratio": round(breadth, 4) if breadth is not None else None,
        "leading": normalized[:5],
        "lagging": list(reversed(normalized[-5:])),
        "limitations": [] if complete else ["sector_sample_incomplete"],
    }


def _full_market_distribution(stocks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    counts = {label: 0 for label in ("涨停", "涨幅>5%", "涨幅0~5%", "平盘", "跌幅0~5%", "跌幅>5%", "跌停")}
    for code, stock in stocks.items():
        if not is_research_stock_code(code):
            continue
        change = (stock.get("quote") or {}).get("change_pct")
        try:
            value = float(change)
        except (TypeError, ValueError):
            continue
        label = (
            "涨停" if value >= 9.8 else "涨幅>5%" if value > 5 else "涨幅0~5%" if value > 0
            else "跌停" if value <= -9.8 else "跌幅>5%" if value < -5 else "跌幅0~5%" if value < 0 else "平盘"
        )
        counts[label] += 1
    return [{"label": label, "count": count} for label, count in counts.items()]


def _market_sentiment(market: dict[str, Any], index_avg: float, main_net: float) -> dict[str, Any]:
    """使用市场广度、指数和资金计算可复核的市场情绪。"""
    counts = {str(row.get("label")): int(_f(row.get("count"))) for row in (market.get("market_distribution") or [])}
    advancing = counts.get("涨停", 0) + counts.get("涨幅>5%", 0) + counts.get("涨幅0~5%", 0)
    declining = counts.get("跌停", 0) + counts.get("跌幅>5%", 0) + counts.get("跌幅0~5%", 0)
    breadth_total = advancing + declining + counts.get("平盘", 0)
    breadth = (advancing - declining) / breadth_total if breadth_total else None
    score = 50.0 + index_avg * 6.0 + max(-15.0, min(15.0, main_net / 20.0))
    if breadth is not None:
        score += breadth * 25.0
    score = round(max(0.0, min(100.0, score)), 2)
    label = "偏热" if score >= 65 else "偏冷" if score <= 35 else "中性"
    degraded = bool(market.get("degraded")) or breadth_total < 100
    return {
        "score": score,
        "label": label,
        "advancing_count": advancing,
        "declining_count": declining,
        "breadth": round(breadth, 4) if breadth is not None else None,
        "index_avg_change_pct": round(index_avg, 2),
        "main_net_yi": main_net,
        "status": "degraded" if degraded else "valid",
        "limitations": list(dict.fromkeys(
            list(market.get("limitations") or [])
            + (["market_breadth_sample_incomplete"] if breadth_total < 100 else [])
        )),
    }


def _valuation_score(enhance: dict[str, Any]) -> float:
    fundamentals = enhance.get("fundamentals") or {}
    pe = _f(fundamentals.get("pe_ttm"), 999)
    pb = _f(fundamentals.get("pb"), 999)
    if pe <= 35 and pb <= 4:
        return 70.0
    if pe <= 70 and pb <= 8:
        return 55.0
    if pe <= 120 and pb <= 15:
        return 42.0
    return 25.0


def _daily_filter(
    *,
    context: dict[str, Any],
    stock: dict[str, Any],
    enhance: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the deterministic, end-of-day portion of the tail-session filter."""
    strong = context.get("regime") == "偏强"
    profile = "strong" if strong else "weak"
    limits = {
        "change": (4.0, 6.0) if strong else (3.0, 5.0),
        "float_cap": (50.0, 200.0) if strong else (50.0, 300.0),
        "turnover": (5.0, 10.0) if strong else (4.0, 12.0),
        "volume_ratio": (1.5, 2.5) if strong else (1.2, 2.0),
    }
    quote = stock.get("quote") or {}
    analysis = stock.get("analysis") or {}
    ma = analysis.get("ma") or {}
    fundamentals = enhance.get("fundamentals") or {}
    values = {
        "change_pct": snapshot.get("change_pct", quote.get("change_pct")),
        "float_cap_yi": snapshot.get("float_cap_yi", fundamentals.get("float_cap_yi")),
        "turnover_pct": snapshot.get(
            "turnover_pct", analysis.get("turnover", quote.get("turnover"))
        ),
        "volume_ratio_5d": snapshot.get("volume_ratio_5d"),
        "relative_strength_pct": snapshot.get("relative_strength_pct"),
        "close": snapshot.get("close", quote.get("close")),
        "ma5": ma.get("ma5"),
        "ma10": ma.get("ma10"),
        "ma20": ma.get("ma20"),
    }
    blockers: list[str] = []

    def required(name: str, label: str) -> float | None:
        value = values.get(name)
        if value is None:
            blockers.append(f"每日量价筛选缺少{label}")
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            blockers.append(f"每日量价筛选{label}无效")
            return None

    change = required("change_pct", "涨跌幅")
    float_cap = required("float_cap_yi", "流通市值")
    turnover = required("turnover_pct", "换手率")
    volume_ratio = required("volume_ratio_5d", "5日量比")
    relative = required("relative_strength_pct", "相对大盘强度")
    close = required("close", "收盘价")
    ma5 = required("ma5", "MA5")
    ma10 = required("ma10", "MA10")
    ma20 = required("ma20", "MA20")
    for value, key, label in (
        (change, "change", "涨幅"),
        (float_cap, "float_cap", "流通市值"),
        (turnover, "turnover", "换手率"),
    ):
        low, high = limits[key]
        if value is not None and not low < value < high:
            blockers.append(f"{label}未满足{low:g}<{label}<{high:g}")
    low_ratio, high_ratio = limits["volume_ratio"]
    if volume_ratio is not None and not low_ratio <= volume_ratio <= high_ratio:
        blockers.append(f"量比未满足{low_ratio:g}≤量比≤{high_ratio:g}")
    if relative is not None and relative <= 0:
        blockers.append("走势未强于大盘")
    if None not in (close, ma5, ma10, ma20):
        if not (ma5 > ma10 > ma20):
            blockers.append("5/10/20日均线未形成多头排列")
        if not (close > ma5 and close > ma10 and close > ma20):
            blockers.append("股价未站稳5/10/20日均线上方")

    volumes = []
    for row in (stock.get("kline") or [])[-3:]:
        try:
            volumes.append(float(row.get("volume")))
        except (TypeError, ValueError):
            volumes = []
            break
    if len(volumes) < 3:
        blockers.append("每日量价筛选缺少连续3日成交量")
    elif not volumes[0] < volumes[1] < volumes[2]:
        blockers.append("成交量未呈连续3日台阶式温和放量")

    numerical_blockers = list(dict.fromkeys(blockers))
    intraday = snapshot.get("intraday_checks") or {}
    required_intraday = (
        ("stock_above_vwap_all_day", "个股全天站稳分时均价"),
        ("no_tail_pulse", "无尾盘脉冲诱多"),
        ("market_above_vwap_all_day", "大盘全天站稳分时均价"),
        ("market_no_tail_drop", "大盘尾盘无跳水"),
    )
    for key, label in required_intraday:
        if intraday.get(key) is not True:
            blockers.append(
                f"分时数据缺失，无法确认{label}"
                if key not in intraday
                else f"{label}未通过"
            )

    unique_blockers = list(dict.fromkeys(blockers))
    limit_payload = {key: list(bounds) for key, bounds in limits.items()}
    exclusion = _classify_exclusion(unique_blockers, values=values, limits=limit_payload)
    return {
        "profile": profile,
        "profile_label": "强势市场" if strong else "弱势市场",
        "passed": not unique_blockers,
        "numerical_passed": not numerical_blockers,
        "values": values,
        "limits": limit_payload,
        "blockers": unique_blockers,
        "exclusion": exclusion,
        "preferred_check": {
            "label": "14:30后创新高并回踩分时均线不破",
            "passed": intraday.get("late_high_pullback_holds"),
            "required": False,
        },
    }


def _aggressive_filter(
    *,
    context: dict[str, Any],
    stock: dict[str, Any],
    enhance: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """筛选强市中的高换手、放量突破标的，缺少证据时关闭推荐。"""
    quote = stock.get("quote") or {}
    analysis = stock.get("analysis") or {}
    ma = analysis.get("ma") or {}
    fundamentals = enhance.get("fundamentals") or {}
    values = {
        "change_pct": snapshot.get("change_pct", quote.get("change_pct")),
        "float_cap_yi": snapshot.get("float_cap_yi", fundamentals.get("float_cap_yi")),
        "turnover_pct": snapshot.get(
            "turnover_pct", analysis.get("turnover", quote.get("turnover"))
        ),
        "volume_ratio_5d": snapshot.get("volume_ratio_5d"),
        "relative_strength_pct": snapshot.get("relative_strength_pct"),
        "close": snapshot.get("close", quote.get("close")),
        "ma5": ma.get("ma5"),
        "ma10": ma.get("ma10"),
        "ma20": ma.get("ma20"),
    }
    limits = {
        "change": (4.0, 9.5),
        "float_cap": (30.0, 200.0),
        "turnover": (8.0, 25.0),
        "volume_ratio": (1.5, 4.0),
    }
    blockers: list[str] = []
    if context.get("regime") != "偏强":
        blockers.append("激进板仅在偏强市场开放")
    if _f((context.get("sentiment") or {}).get("score")) < 65:
        blockers.append("市场情绪未达到偏热门槛")

    def required(name: str, label: str) -> float | None:
        value = values.get(name)
        if value is None:
            blockers.append(f"激进板筛选缺少{label}")
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            blockers.append(f"激进板筛选{label}无效")
            return None

    change = required("change_pct", "涨跌幅")
    float_cap = required("float_cap_yi", "流通市值")
    turnover = required("turnover_pct", "换手率")
    volume_ratio = required("volume_ratio_5d", "5日量比")
    relative = required("relative_strength_pct", "相对大盘强度")
    close = required("close", "收盘价")
    ma5 = required("ma5", "MA5")
    ma10 = required("ma10", "MA10")
    ma20 = required("ma20", "MA20")
    for value, key, label in (
        (change, "change", "涨幅"),
        (float_cap, "float_cap", "流通市值"),
        (turnover, "turnover", "换手率"),
        (volume_ratio, "volume_ratio", "量比"),
    ):
        low, high = limits[key]
        if value is not None and not low <= value <= high:
            blockers.append(f"{label}未满足{low:g}≤{label}≤{high:g}")
    if relative is not None and relative < 1.0:
        blockers.append("相对大盘强度低于1个百分点")
    if None not in (close, ma5, ma10, ma20):
        if not (close > ma5 > ma10 > ma20):
            blockers.append("股价与5/10/20日均线未形成强势多头排列")

    bars = stock.get("kline") or []
    prior_bars = bars[-61:-1] if len(bars) >= 2 else []
    prior_highs = [
        _f(row.get("high") or row.get("close"))
        for row in prior_bars
        if _f(row.get("high") or row.get("close")) > 0
    ]
    if close is None or not prior_highs:
        blockers.append("激进板筛选缺少历史突破区间")
    elif close <= max(prior_highs):
        blockers.append("收盘价未突破近60日高点")

    volumes = [_f(row.get("volume")) for row in bars[-3:]]
    if len(volumes) < 3 or any(value <= 0 for value in volumes):
        blockers.append("激进板筛选缺少连续3日成交量")
    elif not volumes[0] < volumes[1] < volumes[2]:
        blockers.append("成交量未呈连续3日台阶式放量")

    numerical_blockers = list(dict.fromkeys(blockers))
    intraday = snapshot.get("intraday_checks") or {}
    for key, label in (
        ("stock_above_vwap_all_day", "个股全天站稳分时均价"),
        ("no_tail_pulse", "无尾盘脉冲诱多"),
        ("market_above_vwap_all_day", "大盘全天站稳分时均价"),
        ("market_no_tail_drop", "大盘尾盘无跳水"),
    ):
        if intraday.get(key) is not True:
            blockers.append(f"{label}未通过" if key in intraday else f"分时数据缺失，无法确认{label}")

    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "profile": "aggressive",
        "profile_label": "激进板",
        "passed": not unique_blockers,
        "numerical_passed": not numerical_blockers,
        "values": values,
        "limits": limits,
        "blockers": unique_blockers,
        "exclusion": _classify_exclusion(unique_blockers, values=values, limits=limits),
        "risk_control": {
            "position": "轻仓分批，首次仓位不超过计划资金的一半",
            "stop_loss_pct": -4.0,
            "add_position": "仅允许一次等额补仓，继续下跌则停止补仓并退出",
            "max_holding_days": 5,
        },
    }


def _tail_sector_filter(
    *, context: dict[str, Any], stock: dict[str, Any], enhance: dict[str, Any],
    snapshot: dict[str, Any], sector: dict[str, Any],
) -> dict[str, Any]:
    """尾盘板块 T+1 代理筛选：只使用已落盘的日线/快照，严禁伪造实时确认。"""
    quote = stock.get("quote") or {}
    ma = (stock.get("analysis") or {}).get("ma") or {}
    values = {
        "change_pct": snapshot.get("change_pct", quote.get("change_pct")),
        "close": snapshot.get("close", quote.get("close")),
        "ma5": ma.get("ma5"), "ma20": ma.get("ma20"),
        "relative_strength_pct": snapshot.get("relative_strength_pct"),
        "sector_change_pct": sector.get("change_pct"),
    }
    blockers: list[str] = []
    try:
        change = float(values["change_pct"])
        close = float(values["close"])
        ma5 = float(values["ma5"])
        ma20 = float(values["ma20"])
        sector_change = float(values["sector_change_pct"])
    except (TypeError, ValueError):
        blockers.append("尾盘板块筛选缺少价格、均线或板块数据")
        change = close = ma5 = ma20 = sector_change = 0.0
    if not (sector_change > 0): blockers.append("所属板块当日未上涨")
    if not (0.5 <= change <= 8.0): blockers.append("个股涨幅不在尾盘温和强势区间")
    if not (close > ma20 and ma5 >= ma20): blockers.append("趋势未站稳MA20")
    if values.get("relative_strength_pct") is not None and float(values["relative_strength_pct"]) < 0:
        blockers.append("相对板块/大盘强度不足")
    return {
        "profile": "tail_sector", "profile_label": "尾盘板块T+1",
        "passed": not blockers, "numerical_passed": not blockers,
        "values": values, "blockers": blockers,
        "risk_control": {"position": "模拟小仓位", "stop_loss_pct": -3.0, "max_holding_days": 1,
                          "exit_rule": "下一交易日早盘分批卖出，非实时自动下单"},
    }


def _score(
    period: str,
    *,
    selector: dict[str, Any],
    prediction: dict[str, Any],
    factors: dict[str, Any],
    stock: dict[str, Any],
    impact: dict[str, Any],
    enhance: dict[str, Any],
    replay: dict[str, Any],
    market_adjustment: float,
    sector: dict[str, Any] | None = None,
) -> float:
    fv = factors.get("factors") or {}
    analysis = stock.get("analysis") or {}
    returns = analysis.get("returns") or {}
    selector_score = _f(selector.get("upside_score"))
    factor_score = _f(fv.get("multi_factor_score", fv.get("technical_score", 50)), 50)
    technical_score = _f(fv.get("technical_score"), 50)
    trust = fv.get("price_volume_trust") or {}
    trust_bonus = 4.0 if trust.get("price_trust") and trust.get("volume_trust") else 1.5 if trust.get("price_trust") or trust.get("volume_trust") else 0.0
    technical_score = min(100.0, technical_score + trust_bonus)
    impact_score = 50 + _f(impact.get("impact_score")) * 0.7
    # 政策催化：仅使用结构化公告/事件产物；AI解析结果不能直接改分。
    policy = impact.get("policy_catalyst") or impact.get("policy_score")
    policy_score = max(0.0, min(100.0, _f(policy, 50.0))) if policy is not None else 50.0
    # 资金聚集：使用主力净流入和板块成交强度，限制单项贡献避免追高。
    sector_change = _f((sector or {}).get("change_pct"))
    fund_score = max(0.0, min(100.0, 50.0 + _f((impact.get("fund_flow") or {}).get("main_net")) / 2.0))
    replay_score = _f((replay.get("summary") or {}).get("hit_rate"), 0.5) * 100
    valuation = _valuation_score(enhance)
    prediction_score = _f(prediction.get("probability"), 0.5) * 100
    if prediction.get("direction") == "down":
        prediction_score = 100 - prediction_score
    elif prediction.get("direction") == "neutral":
        prediction_score = min(prediction_score, 52)

    if period in {"short", "aggressive"}:
        raw = (
            selector_score * 0.30 + prediction_score * 0.25 + technical_score * 0.20
            + (50 + _f(returns.get("d5")) * 1.5) * 0.10 + replay_score * 0.10
            + impact_score * 0.04 + policy_score * 0.03 + fund_score * 0.03
        )
        raw += market_adjustment
    elif period == "medium":
        raw = (
            factor_score * 0.30 + selector_score * 0.20 + (50 + _f(returns.get("d20"))) * 0.20
            + impact_score * 0.12 + policy_score * 0.04 + fund_score * 0.04 + valuation * 0.05
        )
        raw += market_adjustment * 0.5
    else:
        raw = (
            factor_score * 0.25 + (50 + _f(returns.get("d60")) * 0.15) * 0.20
            + impact_score * 0.16 + policy_score * 0.04 + fund_score * 0.05 + valuation * 0.25 + replay_score * 0.10
        )
    # 新增要素后统一归一化，避免权重总和变化导致评分整体漂移。
    return round(max(0.0, min(100.0, raw / 1.05)), 2)


def _blockers(
    period: str,
    selector: dict[str, Any],
    prediction: dict[str, Any],
    impact: dict[str, Any],
    stock: dict[str, Any],
    replay: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    name = str(stock.get("name") or "")
    if "ST" in name.upper() or "退" in name:
        blockers.append("ST或退市风险标的不进入正式推荐")
    quality = _f((stock.get("quality") or {}).get("quality_score"), 100)
    if quality < 70:
        blockers.append("数据质量低于70分")
    if period == "short" and selector.get("status") == "rejected":
        blockers.extend(selector.get("reject_reasons") or ["上涨候选筛选未通过"])
    if period == "short" and prediction.get("direction") == "down":
        blockers.append("短线预测方向偏空")
    if period == "medium" and _f(impact.get("impact_score")) <= -25:
        blockers.append("中线实际影响显著偏负面")
    if period == "long" and _f(impact.get("impact_score")) <= -30:
        blockers.append("中长期实际影响显著偏负面")
    summary = replay.get("summary") or {}
    # Legacy/unit fixtures may only expose hit_rate. Enforce the full gate once
    # five-year sample and return fields are present.
    if "evaluated_count" in summary and "avg_return_pct" in summary:
        samples = int(summary.get("evaluated_count") or 0)
        hit_rate = _f(summary.get("hit_rate"))
        avg_return = _f(summary.get("avg_return_pct"))
        thresholds = {
            "short": (500, 0.52, 0.0),
            "medium": (500, 0.55, 1.0),
            "long": (500, 0.52, 0.0),
        }
        minimum_samples, minimum_hit_rate, minimum_return = thresholds[period]
        if samples < minimum_samples:
            blockers.append(f"五年验证样本不足{minimum_samples}")
        if hit_rate < minimum_hit_rate:
            blockers.append(f"五年验证命中率低于{minimum_hit_rate * 100:.0f}%")
        if avg_return < minimum_return:
            blockers.append(f"五年平均方向收益低于{minimum_return:.0f}%")
    return list(dict.fromkeys(blockers))


def _evidence(
    period: str,
    selector: dict[str, Any],
    factors: dict[str, Any],
    stock: dict[str, Any],
    impact: dict[str, Any],
    replay: dict[str, Any],
    context: dict[str, Any],
    sector: dict[str, Any] | None = None,
) -> list[str]:
    fv = factors.get("factors") or {}
    returns = (stock.get("analysis") or {}).get("returns") or {}
    days = {"short": "d5", "aggressive": "d5", "tail_sector": "d5", "medium": "d20", "long": "d60"}[period]
    result = [
        f"候选评分 {_f(selector.get('upside_score')):.1f}",
        f"多因子评分 {_f(fv.get('multi_factor_score', fv.get('technical_score', 50))):.1f}",
        f"{days[1:]}日历史涨跌 {_f(returns.get(days)):.2f}%",
        f"实际影响评分 {_f(impact.get('impact_score')):.0f}",
        f"政策催化评分 {_f(impact.get('policy_catalyst', impact.get('policy_score', 50))):.0f}",
        f"资金聚集信号 {_f((impact.get('fund_flow') or {}).get('main_net')):+.2f}",
        f"价托/量托 {(fv.get('price_volume_trust') or {}).get('trust_signal', 'none')}",
        (
            f"市场情绪 {(context.get('sentiment') or {}).get('label', '未知')} "
            f"{_f((context.get('sentiment') or {}).get('score')):.1f}分，"
            f"本周期市场修正 {context.get('score_adjustment', 0):+.1f}分"
        ),
    ]
    summary = replay.get("summary") or {}
    if summary:
        result.append(f"历史策略验证命中率 {_f(summary.get('hit_rate')) * 100:.0f}%")
    if sector and sector.get("primary_industry"):
        change = sector.get("change_pct")
        matched = sector.get("matched_industry") or sector["primary_industry"]
        result.append(
            f"所属行业 {sector['primary_industry']}（行情匹配：{matched}），"
            + (f"板块当日涨跌 {_f(change):+.2f}%" if change is not None else "板块行情待匹配")
        )
    return result


def build_recommendation_payload(
    *,
    market: dict[str, Any],
    stocks: dict[str, dict[str, Any]],
    selectors: dict[str, dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    factors: dict[str, dict[str, Any]],
    impacts: dict[str, dict[str, Any]],
    enhances: dict[str, dict[str, Any]],
    replays: dict[str, dict[str, Any]],
    daily_snapshots: dict[str, dict[str, Any]] | None = None,
    sector_mapping: dict[str, dict[str, Any]] | None = None,
    limit: int = 5,
    track_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_for_analysis = dict(market)
    derived_distribution = _full_market_distribution(stocks)
    if sum(item["count"] for item in derived_distribution) >= 100:
        market_for_analysis["market_distribution"] = derived_distribution
        # Full local breadth repairs a generic incomplete-market flag, while
        # explicit freshness/source limitations must remain degraded.
        market_for_analysis["degraded"] = bool(market_for_analysis.get("limitations"))
    context = _market_context(market_for_analysis)
    sector_mapping = sector_mapping or {}
    daily_snapshots = daily_snapshots or {}
    sector_changes = {
        row["name"]: row["change_pct"]
        for row in (context.get("sector_market") or {}).get("leading", [])
        + (context.get("sector_market") or {}).get("lagging", [])
    }
    period_results: dict[str, Any] = {}
    aggressive_parallel: dict[str, list[dict[str, Any]]] = {lane: [] for lane in AGGRESSIVE_LANES}
    for period, spec in PERIODS.items():
        evaluated: list[dict[str, Any]] = []
        for code, stock in stocks.items():
            # 只保留普通 A 股权限可交易的标的；额外权限板块不进入任何候选集合。
            if not is_research_stock_code(code):
                continue
            selector = selectors.get(code) or {}
            prediction = predictions.get(code) or {}
            factor = factors.get(code) or {}
            impact = impacts.get(code) or {}
            enhance = enhances.get(code) or {}
            replay = replays.get(code) or {}
            sector = dict(sector_mapping.get(code) or {})
            matched_industry = next(
                (
                    name for name in reversed(sector.get("industries") or [])
                    if name in sector_changes
                ),
                str(sector.get("primary_industry") or ""),
            )
            sector["matched_industry"] = matched_industry
            sector["change_pct"] = sector_changes.get(matched_industry)
            if period == "aggressive":
                daily_filter = _aggressive_filter(
                    context=context, stock=stock, enhance=enhance,
                    snapshot=daily_snapshots.get(code) or {},
                )
            elif period == "tail_sector":
                daily_filter = _tail_sector_filter(
                    context=context, stock=stock, enhance=enhance,
                    snapshot=daily_snapshots.get(code) or {}, sector=sector,
                )
            else:
                daily_filter = _daily_filter(
                    context=context, stock=stock, enhance=enhance,
                    snapshot=daily_snapshots.get(code) or {},
                )
            # 每日推荐完全由用户定义的市场自适应筛选决定；旧评分只作为排序参考，
            # 不再参与是否推荐的判定。
            legacy_score = _score(
                period, selector=selector, prediction=prediction, factors=factor, stock=stock,
                impact=impact, enhance=enhance, replay=replay, sector=sector,
                market_adjustment=context["score_adjustment"],
            )
            score = 100.0 if daily_filter["passed"] else 0.0
            blockers = list(daily_filter["blockers"])
            threshold = spec["threshold"]
            status = "recommended" if daily_filter["passed"] else "excluded"
            formal_recommendation = period not in {"aggressive", "tail_sector"}
            evaluated.append({
                "code": code,
                "name": stock.get("name") or selector.get("name") or code,
                "period": spec["label"],
                "horizon": spec["horizon"],
                "score": score,
                "legacy_score": legacy_score,
                "status": status,
                "formal_recommendation": formal_recommendation,
                "evidence": _evidence(period, selector, factor, stock, impact, replay, context, sector),
                "sector_context": sector,
                "risks": list(dict.fromkeys((selector.get("risks") or []) + blockers)),
                "invalidation_conditions": [
                    "任一强弱市场筛选硬条件不再满足",
                    "分时数据缺失或尾盘确认条件不通过",
                ],
                "reevaluation_conditions": selector.get("next_triggers") or ["数据或趋势发生显著变化时重新评估"],
                "replay_summary": replay.get("summary") or {},
                "daily_filter": daily_filter,
                "risk_control": daily_filter.get("risk_control") or {},
            })
            if period == "aggressive":
                values = daily_filter.get("values") or {}
                change = _f(values.get("change_pct"), -99)
                volume_ratio = _f(values.get("volume_ratio_5d"), 0)
                close = _f(values.get("close"), 0)
                ma5, ma20 = values.get("ma5"), values.get("ma20")
                sector_change = _f(sector.get("change_pct"), -99)
                relative = _f(values.get("relative_strength_pct"), -99)
                lane_rules = {
                    "momentum_breakout": change >= 2 and volume_ratio >= 1.2 and close > _f(ma20, 1e99),
                    "trend_pullback": ma5 is not None and ma20 is not None and close > _f(ma20, 1e99) and float(ma5) > float(ma20) and abs(close / float(ma20) - 1) <= .03,
                    "sector_leader": sector_change > 0 and relative >= 0,
                }
                for lane, passed in lane_rules.items():
                    if passed:
                        lane_item = dict(evaluated[-1])
                        lane_item.update({"strategy_lane": lane, "status": "aggressive_observation", "formal_recommendation": False, "risk_level": "high"})
                        lane_item["lane_score"] = round(float(legacy_score) + (sector_change if lane == "sector_leader" else 0), 2)
                        aggressive_parallel[lane].append(lane_item)
        evaluated.sort(
            key=lambda item: (item["daily_filter"]["passed"], item["legacy_score"]),
            reverse=True,
        )
        recommendations = [x for x in evaluated if x["status"] == "recommended"][:limit]
        watches: list[dict[str, Any]] = []
        if period == "aggressive":
            # 独立激进观察池：放宽正式短线条件，但不伪装成正式推荐。
            # 以综合分、阻断项数量和数据质量排序，确保有可供人工复核的候选。
            ranked_watch = sorted(
                evaluated,
                key=lambda item: (
                    -float(item.get("legacy_score") or 0),
                    len(item.get("daily_filter", {}).get("blockers") or []),
                    item.get("code", ""),
                ),
            )
            for item in ranked_watch[:limit]:
                watch = dict(item)
                watch["status"] = "aggressive_observation"
                watch["risk_level"] = "high"
                watch["formal_recommendation"] = False
                watch["relaxed_reason"] = "放宽分时、量价和市场环境条件，仅用于盘后人工复核"
                watch["risks"] = list(dict.fromkeys([
                    *(watch.get("risks") or []),
                    "激进观察池不代表正式买入信号",
                    "必须小仓位并设置止损",
                ]))
                watches.append(watch)
        shortage = max(0, limit - len(recommendations))
        period_results[period] = {
            **spec,
            "recommendations": recommendations,
            "observation": watches,
            "evaluated": evaluated,
            "shortage_count": shortage,
            "shortage_reason": "" if not shortage else (
                f"仅有{len(recommendations)}只完全通过{spec['label']}条件，不为凑满{limit}只而放宽标准"
            ),
        }
    for lane, rows in aggressive_parallel.items():
        rows.sort(key=lambda item: (-float(item.get("lane_score") or 0), item.get("code", "")))
        aggressive_parallel[lane] = rows[:limit]
    aggressive_board = period_results.get("aggressive", {}).get("observation") or []
    # 数据字段缺失时也保留一个可人工复核的回退候选，避免单条激进流无输出。
    for lane, rows in aggressive_parallel.items():
        if not rows and aggressive_board:
            fallback = dict(aggressive_board[0])
            fallback.update({"strategy_lane": lane, "lane_fallback": True, "formal_recommendation": False})
            aggressive_parallel[lane] = [fallback]
    miss_audit = build_miss_audit(period_results, context)
    strategy_router = apply_route_evidence(route_market_regime(context), track_evidence, context)
    return {
        "recommendation_version": RECOMMENDATION_VERSION,
        "updated_at": now_str(),
        "selection_policy": "market_adaptive_daily_and_aggressive_filters_anti_chase",
        "anti_chase_policy": ANTI_CHASE_POLICY,
        "market_context": context,
        "strategy_router": strategy_router,
        "periods": period_results,
        "aggressive_parallel": {
            "lanes": aggressive_parallel,
            "policy": "三条激进策略独立计算，仅作高风险观察，不进入正式评分",
        },
        "aggressive_board": {
            "status": "available" if aggressive_board else "empty_data",
            "label": "激进观察板（非正式推荐）",
            "candidates": aggressive_board,
            "guarantee": "只要研究股票池存在候选，激进观察板不因正式条件为空而为空",
        },
        "miss_audit": miss_audit,
        "limitations": [x for x in [
            "additional_permission_boards_excluded_from_all_candidate_periods",
            "recommendation_universe_limited_to_locally_available_stock_artifacts",
            "legacy_scores_are_ranking_only_and_do_not_gate_daily_recommendations",
            "same_day_large_gainers_excluded_by_anti_chase_design",
            "degraded_market_or_fund_flow_data_may_reduce_confidence" if context["degraded"] else "",
        ] if x],
    }
