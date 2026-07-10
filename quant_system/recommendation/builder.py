"""构建短线、中线和长线推荐。"""

from __future__ import annotations

from typing import Any

from quant_system.utils.time_utils import now_str

RECOMMENDATION_VERSION = "1.0.0"
PERIODS = {
    "short": {"label": "短线", "horizon": "1-5个交易日", "threshold": 58.0},
    "medium": {"label": "中线", "horizon": "1-3个月", "threshold": 60.0},
    "long": {"label": "长线", "horizon": "6-12个月", "threshold": 62.0},
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
    return {
        "trade_date": market.get("trade_date"),
        "regime": regime,
        "index_avg_change_pct": round(avg_change, 2),
        "main_net_yi": main_net,
        "score_adjustment": adjustment,
        "degraded": bool(market.get("degraded")),
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
) -> float:
    fv = factors.get("factors") or {}
    analysis = stock.get("analysis") or {}
    returns = analysis.get("returns") or {}
    selector_score = _f(selector.get("upside_score"))
    factor_score = _f(fv.get("multi_factor_score", fv.get("technical_score", 50)), 50)
    technical_score = _f(fv.get("technical_score"), 50)
    impact_score = 50 + _f(impact.get("impact_score")) * 0.7
    replay_score = _f((replay.get("summary") or {}).get("hit_rate"), 0.5) * 100
    valuation = _valuation_score(enhance)
    prediction_score = _f(prediction.get("probability"), 0.5) * 100
    if prediction.get("direction") == "down":
        prediction_score = 100 - prediction_score
    elif prediction.get("direction") == "neutral":
        prediction_score = min(prediction_score, 52)

    if period == "short":
        raw = (
            selector_score * 0.30 + prediction_score * 0.25 + technical_score * 0.20
            + (50 + _f(returns.get("d5")) * 1.5) * 0.10 + replay_score * 0.10
            + impact_score * 0.05
        )
        raw += market_adjustment
    elif period == "medium":
        raw = (
            factor_score * 0.30 + selector_score * 0.20 + (50 + _f(returns.get("d20"))) * 0.20
            + impact_score * 0.15 + replay_score * 0.10 + valuation * 0.05
        )
        raw += market_adjustment * 0.5
    else:
        raw = (
            factor_score * 0.25 + (50 + _f(returns.get("d60")) * 0.15) * 0.20
            + impact_score * 0.20 + valuation * 0.25 + replay_score * 0.10
        )
    return round(max(0.0, min(100.0, raw)), 2)


def _blockers(period: str, selector: dict[str, Any], prediction: dict[str, Any], impact: dict[str, Any], stock: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
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
    return list(dict.fromkeys(blockers))


def _evidence(period: str, selector: dict[str, Any], factors: dict[str, Any], stock: dict[str, Any], impact: dict[str, Any], replay: dict[str, Any]) -> list[str]:
    fv = factors.get("factors") or {}
    returns = (stock.get("analysis") or {}).get("returns") or {}
    days = {"short": "d5", "medium": "d20", "long": "d60"}[period]
    result = [
        f"候选评分 {_f(selector.get('upside_score')):.1f}",
        f"多因子评分 {_f(fv.get('multi_factor_score', fv.get('technical_score', 50))):.1f}",
        f"{days[1:]}日历史涨跌 {_f(returns.get(days)):.2f}%",
        f"实际影响评分 {_f(impact.get('impact_score')):.0f}",
    ]
    summary = replay.get("summary") or {}
    if summary:
        result.append(f"十日推演命中率 {_f(summary.get('hit_rate')) * 100:.0f}%")
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
    limit: int = 5,
) -> dict[str, Any]:
    context = _market_context(market)
    period_results: dict[str, Any] = {}
    for period, spec in PERIODS.items():
        evaluated: list[dict[str, Any]] = []
        for code, stock in stocks.items():
            selector = selectors.get(code) or {}
            prediction = predictions.get(code) or {}
            factor = factors.get(code) or {}
            impact = impacts.get(code) or {}
            enhance = enhances.get(code) or {}
            replay = replays.get(code) or {}
            score = _score(
                period, selector=selector, prediction=prediction, factors=factor, stock=stock,
                impact=impact, enhance=enhance, replay=replay,
                market_adjustment=context["score_adjustment"],
            )
            blockers = _blockers(period, selector, prediction, impact, stock)
            threshold = spec["threshold"]
            status = "recommended" if score >= threshold and not blockers else "watch" if score >= threshold - 10 and not blockers else "excluded"
            evaluated.append({
                "code": code,
                "name": stock.get("name") or selector.get("name") or code,
                "period": spec["label"],
                "horizon": spec["horizon"],
                "score": score,
                "status": status,
                "evidence": _evidence(period, selector, factor, stock, impact, replay),
                "risks": list(dict.fromkeys((selector.get("risks") or []) + blockers)),
                "invalidation_conditions": [
                    f"综合评分跌破{threshold:.0f}分",
                    "数据质量低于70分",
                    "实际影响转为显著负面",
                ],
                "reevaluation_conditions": selector.get("next_triggers") or ["数据或趋势发生显著变化时重新评估"],
                "replay_summary": replay.get("summary") or {},
            })
        evaluated.sort(key=lambda item: item["score"], reverse=True)
        recommendations = [x for x in evaluated if x["status"] == "recommended"][:limit]
        watches = [x for x in evaluated if x["status"] == "watch"][:limit]
        shortage = max(0, limit - len(recommendations))
        period_results[period] = {
            **spec,
            "recommendations": recommendations,
            "watchlist": watches,
            "evaluated": evaluated,
            "shortage_count": shortage,
            "shortage_reason": "" if not shortage else f"仅有{len(recommendations)}只通过阈值和硬性风险门禁，不为凑满{limit}只而降低标准",
        }
    return {
        "recommendation_version": RECOMMENDATION_VERSION,
        "updated_at": now_str(),
        "market_context": context,
        "periods": period_results,
        "limitations": [x for x in [
            "recommendation_universe_limited_to_local_watchlist",
            "long_horizon_lacks_dedicated_prediction_model",
            "degraded_market_or_fund_flow_data_may_reduce_confidence" if context["degraded"] else "",
        ] if x],
    }
