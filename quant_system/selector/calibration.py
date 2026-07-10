"""Selector 阈值自动校准。"""

from __future__ import annotations

from typing import Any

CALIBRATION_VERSION = "1.0.0"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded(value: float, low: float, high: float) -> float:
    return max(min(value, high), low)


def _base(mode: str) -> dict[str, Any]:
    return {
        "calibration_version": CALIBRATION_VERSION,
        "mode": mode,
        "score_adjustment": 0.0,
        "candidate_score_delta": 0.0,
        "watch_score_delta": 0.0,
        "probability_floor_delta": 0.0,
        "reasons": [],
        "risk_notes": [],
        "evidence": {},
    }


def _from_review(review: dict[str, Any]) -> dict[str, Any] | None:
    summary = review.get("summary") or {}
    evaluated_count = int(_to_float(summary.get("evaluated_count")))
    if evaluated_count < 3:
        return None

    hit_rate = _to_float(summary.get("hit_rate"), 0.5)
    avg_return_pct = _to_float(summary.get("avg_return_pct"))
    out = _base("review")
    out["evidence"] = {
        "evaluated_count": evaluated_count,
        "hit_rate": hit_rate,
        "avg_return_pct": avg_return_pct,
    }

    if hit_rate < 0.45:
        out["score_adjustment"] = -8.0
        out["candidate_score_delta"] = 5.0
        out["watch_score_delta"] = 3.0
        out["probability_floor_delta"] = 0.03
        out["risk_notes"].append(f"后验命中率偏低 {hit_rate:.0%}，候选阈值上调")
    elif hit_rate > 0.60 and avg_return_pct > 0:
        out["score_adjustment"] = 3.0
        out["candidate_score_delta"] = -2.0
        out["watch_score_delta"] = -1.0
        out["reasons"].append(f"后验命中率 {hit_rate:.0%} 且平均收益为正，阈值小幅放宽")
    else:
        out["reasons"].append(f"后验证据中性，命中率 {hit_rate:.0%}")
    return out


def _from_replay(replay: dict[str, Any]) -> dict[str, Any] | None:
    summary = replay.get("summary") or {}
    learning = replay.get("learning") or {}
    evaluated_count = int(_to_float(summary.get("evaluated_count") or summary.get("step_count")))
    if evaluated_count < 5:
        return None

    hit_rate = _to_float(summary.get("hit_rate"), 0.5)
    false_up_count = int(_to_float(learning.get("false_up_count")))
    false_down_count = int(_to_float(learning.get("false_down_count")))
    miss_reason_distribution = learning.get("miss_reason_distribution") or {}
    out = _base("replay")
    out["evidence"] = {
        "evaluated_count": evaluated_count,
        "hit_rate": hit_rate,
        "false_up_count": false_up_count,
        "false_down_count": false_down_count,
        "miss_reason_distribution": miss_reason_distribution,
    }

    if hit_rate < 0.50:
        out["score_adjustment"] = -6.0
        out["candidate_score_delta"] = 4.0
        out["watch_score_delta"] = 2.0
        out["probability_floor_delta"] = 0.02
        out["risk_notes"].append(f"十日推演命中率偏低 {hit_rate:.0%}，候选阈值上调")
    elif hit_rate > 0.65:
        out["score_adjustment"] = 2.0
        out["candidate_score_delta"] = -1.0
        out["reasons"].append(f"十日推演命中率 {hit_rate:.0%}，阈值小幅放宽")
    else:
        out["reasons"].append(f"十日推演证据中性，命中率 {hit_rate:.0%}")

    if false_up_count > false_down_count:
        out["probability_floor_delta"] = max(out["probability_floor_delta"], 0.03)
        out["risk_notes"].append("历史推演中误判上涨多于误判下跌，需提高向上概率门槛")
    for reason, count in miss_reason_distribution.items():
        if count and ("概率" in reason or "边界" in reason):
            out["probability_floor_delta"] = max(out["probability_floor_delta"], 0.03)
            out["risk_notes"].append("未命中原因包含概率边界问题，需提高预测概率确认")
            break
    return out


def normalize_calibration(calibration: dict[str, Any]) -> dict[str, Any]:
    """限制校准幅度，避免单次复盘样本过度影响 selector。"""
    out = _base(calibration.get("mode") or "manual")
    out.update(calibration)
    out["score_adjustment"] = round(_bounded(_to_float(out.get("score_adjustment")), -12.0, 6.0), 2)
    out["candidate_score_delta"] = round(_bounded(_to_float(out.get("candidate_score_delta")), -4.0, 8.0), 2)
    out["watch_score_delta"] = round(_bounded(_to_float(out.get("watch_score_delta")), -3.0, 5.0), 2)
    out["probability_floor_delta"] = round(_bounded(_to_float(out.get("probability_floor_delta")), 0.0, 0.06), 3)
    out["reasons"] = list(dict.fromkeys(out.get("reasons") or []))
    out["risk_notes"] = list(dict.fromkeys(out.get("risk_notes") or []))
    return out


def build_selector_calibration(
    *,
    review: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """基于后验复盘优先、十日推演兜底生成 selector 校准参数。"""
    if review:
        calibrated = _from_review(review)
        if calibrated:
            return normalize_calibration(calibrated)
    if replay:
        calibrated = _from_replay(replay)
        if calibrated:
            return normalize_calibration(calibrated)

    out = _base("neutral")
    out["risk_notes"].append("后验复盘样本不足，selector 阈值保持默认")
    return out
