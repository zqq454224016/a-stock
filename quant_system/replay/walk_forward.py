"""十日前视角的逐日滚动推演。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.factors.signal import compute_primary_signal
from quant_system.factors.technical import compute_technical_factors
from quant_system.prediction.verified import build_verified_prediction
from quant_system.utils.time_utils import now_str

REPLAY_VERSION = "1.1.0"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(row: pd.Series) -> str:
    value = row["date"]
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _actual_direction(ret: float, threshold: float = 0.003) -> str:
    if ret >= threshold:
        return "up"
    if ret <= -threshold:
        return "down"
    return "neutral"


def _hit(pred_direction: str, actual_direction: str) -> bool | None:
    if pred_direction == "neutral":
        return actual_direction == "neutral"
    if actual_direction == "neutral":
        return None
    return pred_direction == actual_direction


def _cause(
    category: str,
    label: str,
    effect: str,
    evidence: str,
    *,
    source: str = "technical",
    source_timing: str = "known_at_cutoff",
) -> dict[str, str]:
    return {
        "category": category,
        "label": label,
        "effect": effect,
        "evidence": evidence,
        "source": source,
        "source_timing": source_timing,
    }


def _date_leq(left: Any, right: str) -> bool:
    if not left or not right:
        return False
    return str(left)[:10] <= str(right)[:10]


def _context_timing(payload: dict[str, Any] | None, cutoff: str) -> str:
    if _date_leq((payload or {}).get("trade_date"), cutoff):
        return "known_at_cutoff"
    return "latest_context_review"


def _market_context_causes(market: dict[str, Any] | None, enhance: dict[str, Any] | None, cutoff: str) -> list[dict[str, str]]:
    ctx = market or ((enhance or {}).get("index_context") or {})
    if not ctx:
        return []
    timing = _context_timing(ctx, cutoff)
    causes: list[dict[str, str]] = []
    indices = ctx.get("indices") or ctx.get("benchmarks") or []
    for idx in indices[:4]:
        change = _num(idx.get("change_pct"))
        if abs(change) < 1.0:
            continue
        effect = "bullish" if change > 0 else "bearish"
        causes.append(_cause(
            "market",
            f"{idx.get('name') or idx.get('code')} {'走强' if change > 0 else '走弱'}",
            effect,
            f"指数涨跌幅 {change:.2f}%",
            source="market.indices",
            source_timing=timing,
        ))

    flow = ctx.get("fund_flow") or ctx.get("market_fund_flow") or {}
    main_net = _num(flow.get("main_net"))
    north_net = _num(flow.get("north_net"))
    if main_net <= -100:
        causes.append(_cause("market_fund", "市场主力资金净流出", "bearish", f"主力净流出 {main_net:.2f} 亿", source="market.fund_flow", source_timing=timing))
    elif main_net >= 100:
        causes.append(_cause("market_fund", "市场主力资金净流入", "bullish", f"主力净流入 {main_net:.2f} 亿", source="market.fund_flow", source_timing=timing))
    if north_net <= -30:
        causes.append(_cause("market_fund", "北向资金净流出", "bearish", f"北向净流出 {north_net:.2f} 亿", source="market.fund_flow", source_timing=timing))
    elif north_net >= 30:
        causes.append(_cause("market_fund", "北向资金净流入", "bullish", f"北向净流入 {north_net:.2f} 亿", source="market.fund_flow", source_timing=timing))

    distribution = ctx.get("market_distribution") or []
    up_count = sum(int(x.get("count") or 0) for x in distribution if "涨" in str(x.get("label")))
    down_count = sum(int(x.get("count") or 0) for x in distribution if "跌" in str(x.get("label")))
    if up_count or down_count:
        if down_count > up_count * 1.5:
            causes.append(_cause("market_breadth", "市场宽度偏弱", "bearish", f"上涨 {up_count} 家，下跌 {down_count} 家", source="market.distribution", source_timing=timing))
        elif up_count > down_count * 1.5:
            causes.append(_cause("market_breadth", "市场宽度偏强", "bullish", f"上涨 {up_count} 家，下跌 {down_count} 家", source="market.distribution", source_timing=timing))
    return causes


def _fundamental_context_causes(enhance: dict[str, Any] | None, cutoff: str) -> list[dict[str, str]]:
    if not enhance:
        return []
    timing = _context_timing(enhance, cutoff)
    causes: list[dict[str, str]] = []
    val = enhance.get("fundamentals") or {}
    pe = _num(val.get("pe_ttm"))
    pb = _num(val.get("pb"))
    if pe >= 80 or pb >= 10:
        causes.append(_cause("valuation", "估值压力偏高", "bearish", f"PE(TTM) {pe:.2f}，PB {pb:.2f}", source="enhance.fundamentals", source_timing=timing))
    elif pe and pe <= 20 and pb and pb <= 3:
        causes.append(_cause("valuation", "估值相对可控", "bullish", f"PE(TTM) {pe:.2f}，PB {pb:.2f}", source="enhance.fundamentals", source_timing=timing))

    flow = (enhance.get("fund_flow") or {})
    north = flow.get("northbound") or {}
    margin = flow.get("margin") or {}
    north_net = _num(north.get("net_buy_amount_yi"))
    hold_pct = _num(north.get("hold_pct"))
    if north_net >= 0.5 or hold_pct >= 2:
        causes.append(_cause("stock_fund", "个股北向资金支持", "bullish", f"北向净买 {north_net:.2f} 亿，持股 {hold_pct:.2f}%", source="enhance.northbound", source_timing=timing))
    elif north_net <= -0.5:
        causes.append(_cause("stock_fund", "个股北向资金流出", "bearish", f"北向净买 {north_net:.2f} 亿", source="enhance.northbound", source_timing=timing))
    margin_buy = _num(margin.get("margin_buy_yi"))
    if margin_buy >= 1:
        causes.append(_cause("stock_fund", "融资买入活跃", "bullish", f"融资买入 {margin_buy:.2f} 亿", source="enhance.margin", source_timing=timing))

    forecast = ((enhance.get("corporate") or {}).get("earnings_forecast") or {})
    if forecast:
        change = _num(forecast.get("change_pct"))
        if change >= 30:
            causes.append(_cause("earnings", "业绩预告增长", "bullish", f"预告变动 {change:.2f}%", source="enhance.earnings_forecast", source_timing=_context_timing({"trade_date": forecast.get("announce_date")}, cutoff)))
        elif change < 0:
            causes.append(_cause("earnings", "业绩预告下滑", "bearish", f"预告变动 {change:.2f}%", source="enhance.earnings_forecast", source_timing=_context_timing({"trade_date": forecast.get("announce_date")}, cutoff)))
    return causes


def _impact_context_causes(impact: dict[str, Any] | None, cutoff: str) -> list[dict[str, str]]:
    if not impact:
        return []
    causes: list[dict[str, str]] = []
    for event in (impact.get("events") or [])[:6]:
        score = _num(event.get("impact_score"))
        if abs(score) < 10 and event.get("event_type") != "q2_profit_growth_gap":
            continue
        direction = event.get("impact_direction") or ("positive" if score > 0 else "negative" if score < 0 else "neutral")
        effect = "bullish" if direction == "positive" else "bearish" if direction == "negative" else "neutral"
        evidence_items = event.get("evidence") or []
        evidence = "；".join(str(x) for x in evidence_items[:2]) or f"impact_score {score:.0f}"
        causes.append(_cause(
            "event",
            event.get("title") or event.get("event_type") or "影响事件",
            effect,
            evidence,
            source=f"impact.{event.get('event_type') or 'event'}",
            source_timing=_context_timing({"trade_date": event.get("announce_date") or event.get("period") or impact.get("trade_date")}, cutoff),
        ))
    return causes


def _root_cause_analysis(
    factors: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    *,
    actual_return_pct: float,
    actual_direction: str,
    hit: bool | None,
    knowledge_cutoff: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """用当时可见因子解释涨跌根因，并标记预测失效点。"""
    ma20_bias = _num(factors.get("ma20_bias"))
    rsi14 = _num(factors.get("rsi14"), 50.0)
    macd_hist = _num(factors.get("macd_hist"))
    momentum_20 = _num(factors.get("momentum_20"))
    volume_ratio = _num(factors.get("volume_ratio_20"), 1.0)
    ma_cross = factors.get("ma_cross")
    above_ma20 = bool(factors.get("above_ma20"))
    pred_direction = prediction.get("direction", "neutral")
    pred_prob = _num(prediction.get("probability"), 0.5)

    causes: list[dict[str, str]] = []
    if above_ma20 and ma20_bias >= 1.0:
        causes.append(_cause("trend", "站上 MA20 且存在正乖离", "bullish", f"MA20乖离 {ma20_bias:.2f}%"))
    elif not above_ma20 and ma20_bias <= -1.0:
        causes.append(_cause("trend", "跌破 MA20 且负乖离扩大", "bearish", f"MA20乖离 {ma20_bias:.2f}%"))

    if ma_cross == "golden":
        causes.append(_cause("trend", "均线金叉", "bullish", "MA5 上穿 MA20"))
    elif ma_cross == "death":
        causes.append(_cause("trend", "均线死叉", "bearish", "MA5 下穿 MA20"))

    if macd_hist > 0:
        causes.append(_cause("momentum", "MACD 柱为正", "bullish", f"MACD hist {macd_hist:.4f}"))
    elif macd_hist < 0:
        causes.append(_cause("momentum", "MACD 柱为负", "bearish", f"MACD hist {macd_hist:.4f}"))

    if momentum_20 >= 5:
        causes.append(_cause("momentum", "20 日动量偏强", "bullish", f"momentum_20 {momentum_20:.2f}%"))
    elif momentum_20 <= -5:
        causes.append(_cause("momentum", "20 日动量偏弱", "bearish", f"momentum_20 {momentum_20:.2f}%"))

    if rsi14 >= 70:
        causes.append(_cause("risk", "RSI 超买，存在回落压力", "bearish", f"RSI14 {rsi14:.2f}"))
    elif rsi14 <= 30:
        causes.append(_cause("reversal", "RSI 超卖，存在反弹条件", "bullish", f"RSI14 {rsi14:.2f}"))

    if volume_ratio >= 1.5:
        effect = "bullish" if actual_direction == "up" else "bearish" if actual_direction == "down" else "neutral"
        label = "放量上涨确认" if effect == "bullish" else "放量下跌/分歧放大" if effect == "bearish" else "放量但方向不明"
        causes.append(_cause("volume", label, effect, f"volume_ratio_20 {volume_ratio:.2f}"))

    context = context or {}
    external_causes = (
        _market_context_causes(context.get("market"), context.get("enhance"), knowledge_cutoff)
        + _fundamental_context_causes(context.get("enhance"), knowledge_cutoff)
        + _impact_context_causes(context.get("impact"), knowledge_cutoff)
    )
    causes.extend(external_causes)

    dominant = [
        c for c in causes
        if (actual_direction == "up" and c["effect"] == "bullish")
        or (actual_direction == "down" and c["effect"] == "bearish")
    ][:3]
    if not dominant and causes:
        dominant = causes[:2]

    miss_reasons: list[str] = []
    if hit is False:
        if pred_direction == "up" and actual_direction == "down":
            miss_reasons.append("看多未命中：需要提高买入确认条件，重点检查趋势与放量是否同步")
        elif pred_direction == "down" and actual_direction == "up":
            miss_reasons.append("看空未命中：可能忽略超跌反弹或趋势修复，需要加入反转过滤")
        if pred_prob < 0.58:
            miss_reasons.append("预测概率处于边界区，后续应降低仓位或只观察")
        if signal.get("signal") == "neutral":
            miss_reasons.append("技术信号中性时方向判断不稳定，应进入 no-trade 区间")
        if not dominant:
            miss_reasons.append("当时可见根因不足以解释实际方向，需要补充资金/事件/大盘数据")
        if not external_causes:
            miss_reasons.append("缺少大盘、资金、公告/业绩或产业价格事件根因")

    return {
        "actual_root_causes": dominant,
        "all_observed_causes": causes,
        "external_context_causes": external_causes,
        "miss_reasons": miss_reasons,
        "model_iteration_notes": _iteration_notes(pred_direction, actual_direction, hit, pred_prob, signal),
    }


def _iteration_notes(
    pred_direction: str,
    actual_direction: str,
    hit: bool | None,
    pred_prob: float,
    signal: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    if hit is True:
        notes.append("保留当前有效特征组合，纳入命中样本")
    elif hit is False:
        notes.append("纳入错误样本，后续用于调高/调低方向阈值")
    else:
        notes.append("中性样本不直接计入方向胜负，可用于校准 no-trade 区间")
    if pred_prob < 0.55:
        notes.append("概率低于强信号区，后续不应生成积极买卖动作")
    if signal.get("signal_score") is not None and _num(signal.get("signal_score")) < 55:
        notes.append("技术信号分不足，后续需要更多确认条件")
    if pred_direction != actual_direction and actual_direction != "neutral":
        notes.append("方向偏差样本应进入复盘池，检查大盘、资金和事件数据缺口")
    return notes


def _operation_levels(as_of: pd.Series, factors: dict[str, Any], history: pd.DataFrame) -> dict[str, Any]:
    """生成后续单日价位级建议所需的雏形字段。"""
    close = _num(as_of.get("close"))
    atr = _num(factors.get("atr14"))
    atr_pct = atr / close if close > 0 and atr > 0 else 0.02
    recent = history.tail(20)
    support = _num(recent["low"].min(), close)
    resistance = _num(recent["high"].max(), close)
    trigger_pct = max(0.005, min(0.03, atr_pct * 0.35))
    stop_pct = max(0.015, min(0.06, atr_pct * 1.2))
    take_pct = max(0.025, min(0.10, atr_pct * 1.8))
    return {
        "reference_close": round(close, 4),
        "support_price": round(support, 4),
        "resistance_price": round(resistance, 4),
        "buy_trigger_price": round(close * (1 + trigger_pct), 4),
        "sell_guard_price": round(max(support, close * (1 - stop_pct)), 4),
        "take_profit_watch_price": round(min(resistance, close * (1 + take_pct)), 4),
        "note": "价位为历史推演中的操作细化雏形，需结合当日盘口和风控后才能使用",
    }


def _step(code: str, df: pd.DataFrame, target_idx: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
    history = df.iloc[:target_idx].copy()
    as_of = history.iloc[-1]
    target = df.iloc[target_idx]
    factors_payload = compute_technical_factors(
        history,
        code,
        trade_date=_date(as_of),
        data_version=f"replay_{code}_{_date(as_of).replace('-', '')}",
    )
    factors = factors_payload["factors"]
    signal = compute_primary_signal(factors, code, _date(as_of))
    prediction = build_verified_prediction(
        code,
        history,
        factors,
        backtest=None,
        quality={"quality_score": 100},
        horizon="1d",
        data_version=factors_payload.get("data_version"),
        trade_date=_date(as_of),
        strategy_name="replay_walk_forward",
    )

    prev_close = float(as_of["close"])
    target_close = float(target["close"])
    ret = (target_close / prev_close - 1) if prev_close > 0 else 0.0
    ret_pct = round(ret * 100, 2)
    actual_direction = _actual_direction(ret)
    hit = _hit(prediction.get("direction", "neutral"), actual_direction)
    root_cause = _root_cause_analysis(
        factors,
        signal,
        prediction,
        actual_return_pct=ret_pct,
        actual_direction=actual_direction,
        hit=hit,
        knowledge_cutoff=_date(as_of),
        context=context,
    )
    return {
        "knowledge_cutoff": _date(as_of),
        "target_date": _date(target),
        "as_of_close": round(prev_close, 4),
        "target_close": round(target_close, 4),
        "prediction": {
            "direction": prediction.get("direction"),
            "probability": prediction.get("probability"),
            "confidence": prediction.get("confidence"),
            "expected_return": prediction.get("expected_return"),
            "risk_flags": prediction.get("risk_flags") or [],
            "sample_count": (prediction.get("evidence") or {}).get("sample_count"),
            "state_label": (prediction.get("evidence") or {}).get("state_label"),
        },
        "technical_signal": {
            "signal": signal.get("signal"),
            "signal_score": signal.get("signal_score"),
            "drivers": signal.get("drivers") or [],
        },
        "factor_snapshot": {
            "ma20_bias": factors.get("ma20_bias"),
            "rsi14": factors.get("rsi14"),
            "macd_hist": factors.get("macd_hist"),
            "momentum_20": factors.get("momentum_20"),
            "volume_ratio_20": factors.get("volume_ratio_20"),
            "above_ma20": factors.get("above_ma20"),
            "ma_cross": factors.get("ma_cross"),
        },
        "root_cause": root_cause,
        "operation_levels": _operation_levels(as_of, factors, history),
        "actual": {
            "return_pct": ret_pct,
            "direction": actual_direction,
            "hit": hit,
        },
    }


def _build_learning_summary(steps: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [s for s in steps if (s.get("actual") or {}).get("hit") is not None]
    misses = [s for s in evaluated if (s.get("actual") or {}).get("hit") is False]
    false_up = [
        s for s in misses
        if ((s.get("prediction") or {}).get("direction") == "up" and (s.get("actual") or {}).get("direction") == "down")
    ]
    false_down = [
        s for s in misses
        if ((s.get("prediction") or {}).get("direction") == "down" and (s.get("actual") or {}).get("direction") == "up")
    ]
    cause_counts: dict[str, int] = {}
    miss_reason_counts: dict[str, int] = {}
    for step in steps:
        root = step.get("root_cause") or {}
        for cause in root.get("actual_root_causes") or []:
            key = cause.get("label") or cause.get("category") or "unknown"
            cause_counts[key] = cause_counts.get(key, 0) + 1
        for reason in root.get("miss_reasons") or []:
            miss_reason_counts[reason] = miss_reason_counts.get(reason, 0) + 1

    suggestions: list[str] = []
    hit_rate = (sum(1 for s in evaluated if (s.get("actual") or {}).get("hit")) / len(evaluated)) if evaluated else None
    if hit_rate is not None and hit_rate < 0.5:
        suggestions.append("十日命中率低于 50%，后续应提高信号阈值，并把边界概率样本降级为观察")
    if false_up:
        suggestions.append("存在看多后下跌样本：买入需增加 MA20 站稳、放量确认和大盘风险过滤")
    if false_down:
        suggestions.append("存在看空后上涨样本：卖出/减仓前需检查超跌反弹、MACD 修复和支撑位")
    if not suggestions:
        suggestions.append("当前窗口未暴露明显系统性偏差，继续积累样本后再校准阈值")

    return {
        "miss_count": len(misses),
        "false_up_count": len(false_up),
        "false_down_count": len(false_down),
        "root_cause_distribution": dict(sorted(cause_counts.items(), key=lambda x: x[1], reverse=True)[:8]),
        "miss_reason_distribution": dict(sorted(miss_reason_counts.items(), key=lambda x: x[1], reverse=True)[:8]),
        "hit_rate_improvement_thoughts": suggestions,
        "next_iteration_focus": [
            "将 root_cause 与 hit/miss 绑定，形成特征有效性复盘样本",
            "把低概率、弱技术信号、根因不足的样本归入 no-trade 区间",
            "后续在 decision 中引入 buy_trigger_price、sell_guard_price、take_profit_watch_price",
        ],
    }


def build_replay_payload(
    code: str,
    name: str,
    df: pd.DataFrame,
    *,
    days: int = 10,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从最近 N 个交易日之前开始，逐日只用当时数据推演下一日。"""
    if len(df) < max(30, days + 2):
        return {
            "code": code,
            "name": name or code,
            "replay_version": REPLAY_VERSION,
            "status": "insufficient_data",
            "steps": [],
            "summary": {"step_count": 0, "hit_rate": None},
            "limitations": ["insufficient_kline_history"],
            "updated_at": now_str(),
        }

    work = df.sort_values("date").reset_index(drop=True)
    first_target_idx = max(1, len(work) - days)
    steps = [_step(code, work, i, context=context) for i in range(first_target_idx, len(work))]
    hit_values = [s["actual"]["hit"] for s in steps if s["actual"]["hit"] is not None]
    up_steps = [s for s in steps if s["prediction"]["direction"] == "up"]
    down_steps = [s for s in steps if s["prediction"]["direction"] == "down"]
    learning = _build_learning_summary(steps)
    return {
        "code": code,
        "name": name or code,
        "replay_version": REPLAY_VERSION,
        "status": "ok",
        "mode": "walk_forward_no_future_data",
        "window_days": days,
        "start_knowledge_cutoff": steps[0]["knowledge_cutoff"] if steps else "",
        "end_target_date": steps[-1]["target_date"] if steps else "",
        "steps": steps,
        "summary": {
            "step_count": len(steps),
            "evaluated_count": len(hit_values),
            "hit_count": sum(1 for x in hit_values if x),
            "hit_rate": round(sum(1 for x in hit_values if x) / len(hit_values), 4) if hit_values else None,
            "up_prediction_count": len(up_steps),
            "down_prediction_count": len(down_steps),
            "total_return_pct": round(((float(work.iloc[-1]["close"]) / float(work.iloc[first_target_idx - 1]["close"])) - 1) * 100, 2),
        },
        "learning": learning,
        "limitations": [
            "prediction_is_technical_only",
            "uses_historical_data_available_at_each_cutoff",
            "actual_return_used_only_for_review",
            "external_context_used_for_root_cause_review_not_for_prediction",
            "external_context_may_be_latest_snapshot_when_source_date_after_cutoff",
        ],
        "updated_at": now_str(),
    }
