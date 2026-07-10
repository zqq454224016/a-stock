"""构建上涨候选池评分。"""

from __future__ import annotations

from typing import Any

from quant_system.config.selector_config import SELECTOR_VERSION, SelectorConfig
from quant_system.selector.calibration import build_selector_calibration, normalize_calibration
from quant_system.utils.time_utils import now_str


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _factor_score(factors_payload: dict[str, Any] | None) -> float:
    factors = (factors_payload or {}).get("factors") or {}
    return _to_float(factors.get("multi_factor_score", factors.get("technical_score", 50.0)), 50.0)


def _trend_points(stock: dict[str, Any] | None, factors_payload: dict[str, Any] | None) -> tuple[float, list[str], list[str]]:
    stock = stock or {}
    factors = (factors_payload or {}).get("factors") or {}
    analysis = stock.get("analysis") or {}
    ma_signal = analysis.get("ma_signal") or {}
    returns = analysis.get("returns") or {}
    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    if ma_signal.get("above_ma20"):
        score += 8
        reasons.append("收盘价站上 MA20")
    else:
        risks.append("未站上 MA20")
    if ma_signal.get("above_ma60"):
        score += 6
        reasons.append("收盘价站上 MA60")
    if _to_float(returns.get("d20")) > 0:
        score += 6
        reasons.append("20日动量为正")
    if _to_float(returns.get("d5")) > 0:
        score += 4
        reasons.append("5日动量为正")
    if _to_float(factors.get("macd_hist")) > 0:
        score += 4
        reasons.append("MACD 柱线为正")
    if factors.get("above_ma20") is False:
        score -= 5
    if _to_float(returns.get("d5")) < -10:
        score -= 8
        risks.append("5日跌幅较大")
    return score, reasons, risks


def _prediction_points(prediction: dict[str, Any] | None) -> tuple[float, list[str], list[str]]:
    prediction = prediction or {}
    direction = prediction.get("direction", "neutral")
    probability = _to_float(prediction.get("probability"), 0.5)
    score = (probability - 0.5) * 80
    reasons: list[str] = []
    risks: list[str] = []

    if direction == "up":
        score += 18
        reasons.append(f"预测方向向上，概率 {probability:.2f}")
    elif direction == "down":
        score -= 25
        risks.append(f"预测方向向下，概率 {probability:.2f}")
    else:
        reasons.append(f"预测中性，概率 {probability:.2f}")
    if prediction.get("confidence") == "high":
        score += 4
    if "high_volatility" in (prediction.get("risk_flags") or []):
        score -= 10
        risks.append("预测标记高波动")
    return score, reasons, risks


def _backtest_points(backtest: dict[str, Any] | None, cfg: SelectorConfig) -> tuple[float, list[str], list[str]]:
    if not backtest:
        return -12.0, [], ["缺少回测证据"]
    metrics = backtest.get("metrics") or {}
    sharpe = _to_float(metrics.get("sharpe_ratio"))
    max_dd = _to_float(metrics.get("max_drawdown_pct"))
    win_rate = _to_float(metrics.get("win_rate_pct"))
    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    if sharpe >= cfg.min_sharpe:
        score += min(14, sharpe * 6)
        reasons.append(f"回测夏普 {sharpe:.2f}")
    else:
        score -= 8
        risks.append(f"回测夏普偏低 {sharpe:.2f}")
    if max_dd < cfg.max_acceptable_drawdown_pct:
        score -= 12
        risks.append(f"历史最大回撤较大 {max_dd:.2f}%")
    elif max_dd < 0:
        score += 4
    if win_rate >= 50:
        score += 6
        reasons.append(f"回测胜率 {win_rate:.2f}%")
    elif win_rate < 35:
        score -= 6
        risks.append(f"回测胜率偏低 {win_rate:.2f}%")
    return score, reasons, risks


def _impact_points(impact: dict[str, Any] | None, cfg: SelectorConfig) -> tuple[float, list[str], list[str]]:
    impact = impact or {}
    score = _to_float(impact.get("impact_score"))
    direction = impact.get("impact_direction", "neutral")
    reasons: list[str] = []
    risks: list[str] = []
    points = max(min(score * 0.35, 18), -22)
    if direction == "positive" and score >= cfg.positive_impact_score:
        reasons.append(f"实际影响偏正面，impact_score={score:.0f}")
    if direction == "negative" and score <= cfg.negative_impact_score:
        risks.append(f"实际影响偏负面，impact_score={score:.0f}")
    for limitation in impact.get("limitations") or []:
        risks.append(f"影响数据限制：{limitation}")
    return points, reasons, risks


def _classify(
    score: float,
    reject_reasons: list[str],
    *,
    candidate_threshold: float,
    watch_threshold: float,
) -> str:
    if reject_reasons:
        return "rejected"
    if score >= candidate_threshold:
        return "candidate"
    if score >= watch_threshold:
        return "watch"
    return "weak"


def _candidate_blockers(
    *,
    stock: dict[str, Any],
    prediction: dict[str, Any],
    factor_score: float,
    impact: dict[str, Any] | None,
    cfg: SelectorConfig,
    probability_floor: float,
) -> list[str]:
    analysis = stock.get("analysis") or {}
    ma_signal = analysis.get("ma_signal") or {}
    probability = _to_float(prediction.get("probability"), 0.5)
    impact_score = _to_float((impact or {}).get("impact_score"))
    blockers: list[str] = []
    if prediction.get("direction") != "up" and probability < probability_floor:
        blockers.append("预测尚未形成向上确认")
    elif probability < probability_floor:
        blockers.append(f"预测概率未达到校准确认线 {probability_floor:.2f}")
    if factor_score < cfg.watch_factor_score:
        blockers.append("因子分未达到观察线")
    if not ma_signal.get("above_ma20"):
        blockers.append("趋势未站上 MA20")
    if impact_score < 0:
        blockers.append("实际影响分为负")
    return blockers


def _next_triggers(
    *,
    stock: dict[str, Any],
    prediction: dict[str, Any],
    factor_score: float,
    impact: dict[str, Any] | None,
    backtest: dict[str, Any] | None,
    cfg: SelectorConfig,
    probability_floor: float,
) -> list[str]:
    analysis = stock.get("analysis") or {}
    ma_signal = analysis.get("ma_signal") or {}
    triggers: list[str] = []
    probability = _to_float(prediction.get("probability"), 0.5)
    impact_score = _to_float((impact or {}).get("impact_score"))
    metrics = (backtest or {}).get("metrics") or {}
    max_dd = _to_float(metrics.get("max_drawdown_pct"))

    if prediction.get("direction") == "down":
        triggers.append("预测方向从偏空修复为震荡或偏多")
    if probability < probability_floor:
        triggers.append(f"预测概率提升到 {probability_floor:.2f} 以上")
    if factor_score < cfg.watch_factor_score:
        triggers.append(f"因子分提升到 {cfg.watch_factor_score:.0f} 以上")
    if not ma_signal.get("above_ma20"):
        triggers.append("收盘价重新站上 MA20")
    if impact_score < 0:
        triggers.append("实际影响分修复到非负")
    if backtest and max_dd < cfg.max_acceptable_drawdown_pct:
        triggers.append(f"回测最大回撤收敛到 {abs(cfg.max_acceptable_drawdown_pct):.0f}% 内")
    if not backtest:
        triggers.append("补齐回测证据")
    return list(dict.fromkeys(triggers))


def build_upside_candidate(
    *,
    code: str,
    name: str = "",
    stock: dict[str, Any] | None = None,
    prediction: dict[str, Any] | None = None,
    factors: dict[str, Any] | None = None,
    backtest: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    cfg: SelectorConfig | None = None,
) -> dict[str, Any]:
    """输出单股上涨候选评分。"""
    cfg = cfg or SelectorConfig()
    calibration = normalize_calibration(calibration) if calibration else build_selector_calibration(review=review, replay=replay)
    stock = stock or {}
    prediction = prediction or {}
    quality = quality or {}
    qscore = _to_float(quality.get("quality_score") or (stock.get("quality") or {}).get("quality_score"), 100.0)
    factor_score = _factor_score(factors)
    base_score = 45.0
    reasons: list[str] = []
    risks: list[str] = []
    reject_reasons: list[str] = []

    if qscore < cfg.min_quality_score:
        reject_reasons.append(f"数据质量不足 quality_score={qscore:.0f}")
    if prediction.get("direction") == "down":
        reject_reasons.append("预测方向为偏空")
    if factor_score < cfg.reject_factor_score:
        reject_reasons.append(f"因子分过低 {factor_score:.1f}")
    if _to_float((impact or {}).get("impact_score")) < cfg.negative_impact_score:
        reject_reasons.append("实际影响数据显著偏负面")

    score = base_score
    score += (factor_score - 50.0) * 0.45
    if factor_score >= cfg.watch_factor_score:
        reasons.append(f"因子分 {factor_score:.1f} 达到观察线")
    else:
        risks.append(f"因子分偏低 {factor_score:.1f}")

    for points_fn in (
        lambda: _prediction_points(prediction),
        lambda: _trend_points(stock, factors),
        lambda: _backtest_points(backtest, cfg),
        lambda: _impact_points(impact, cfg),
    ):
        points, rs, rk = points_fn()
        score += points
        reasons.extend(rs)
        risks.extend(rk)

    score += _to_float(calibration.get("score_adjustment"))
    reasons.extend(f"阈值校准：{r}" for r in calibration.get("reasons") or [])
    risks.extend(f"阈值校准：{r}" for r in calibration.get("risk_notes") or [])

    candidate_threshold = cfg.candidate_score + _to_float(calibration.get("candidate_score_delta"))
    watch_threshold = cfg.watch_score + _to_float(calibration.get("watch_score_delta"))
    probability_floor = 0.55 + _to_float(calibration.get("probability_floor_delta"))
    score = round(max(min(score, 100.0), 0.0), 2)
    status = _classify(
        score,
        reject_reasons,
        candidate_threshold=candidate_threshold,
        watch_threshold=watch_threshold,
    )
    candidate_blockers = _candidate_blockers(
        stock=stock,
        prediction=prediction,
        factor_score=factor_score,
        impact=impact,
        cfg=cfg,
        probability_floor=probability_floor,
    )
    if status == "candidate" and candidate_blockers:
        status = "watch"
    next_triggers = _next_triggers(
        stock=stock,
        prediction=prediction,
        factor_score=factor_score,
        impact=impact,
        backtest=backtest,
        cfg=cfg,
        probability_floor=probability_floor,
    )
    return {
        "code": code,
        "name": name or stock.get("name") or code,
        "trade_date": stock.get("trade_date") or prediction.get("trade_date") or "",
        "selector_version": SELECTOR_VERSION,
        "upside_score": score,
        "status": status,
        "rank_bucket": {
            "candidate": "上涨候选",
            "watch": "观察候选",
            "weak": "弱候选",
            "rejected": "排除",
        }[status],
        "reasons": list(dict.fromkeys(reasons)) or ["暂无正面确认"],
        "risks": list(dict.fromkeys(risks)) or ["无额外风险标记"],
        "reject_reasons": list(dict.fromkeys(reject_reasons)),
        "candidate_blockers": candidate_blockers,
        "next_triggers": next_triggers,
        "metrics": {
            "quality_score": qscore,
            "factor_score": factor_score,
            "candidate_score_threshold": round(candidate_threshold, 2),
            "watch_score_threshold": round(watch_threshold, 2),
            "probability_floor": round(probability_floor, 3),
            "prediction_direction": prediction.get("direction", "neutral"),
            "prediction_probability": _to_float(prediction.get("probability"), 0.5),
            "impact_score": _to_float((impact or {}).get("impact_score")),
            "impact_direction": (impact or {}).get("impact_direction", "neutral"),
        },
        "calibration": calibration,
        "updated_at": now_str(),
    }
