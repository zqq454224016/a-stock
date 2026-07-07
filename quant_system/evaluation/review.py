"""预测、候选和决策的后验收益复盘。"""

from __future__ import annotations

from typing import Any

REVIEW_VERSION = "1.0.0"
DEFAULT_HORIZONS = (1, 5, 20)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(row: dict[str, Any]) -> str:
    return str(row.get("date") or "")[:10]


def _find_index(kline: list[dict[str, Any]], trade_date: str) -> int | None:
    for idx, row in enumerate(kline):
        if _date(row) == str(trade_date)[:10]:
            return idx
    return None


def _direction_hit(direction: str, ret_pct: float, threshold: float = 0.3) -> bool | None:
    if direction == "up":
        return ret_pct >= threshold
    if direction == "down":
        return ret_pct <= -threshold
    if direction == "neutral":
        return abs(ret_pct) < threshold
    return None


def _decision_hit(action: str, ret_pct: float, threshold: float = 0.3) -> bool | None:
    if action in ("buy", "hold"):
        return ret_pct >= threshold
    if action in ("reduce", "sell"):
        return ret_pct <= -threshold
    if action == "watch":
        return abs(ret_pct) < 1.0
    return None


def _window_metrics(kline: list[dict[str, Any]], base_idx: int, horizon: int) -> dict[str, Any]:
    target_idx = base_idx + horizon
    if target_idx >= len(kline):
        return {"status": "pending", "horizon": f"{horizon}d", "reason": "future_kline_missing"}

    base = kline[base_idx]
    target = kline[target_idx]
    base_close = _to_float(base.get("close"))
    target_close = _to_float(target.get("close"))
    if base_close <= 0 or target_close <= 0:
        return {"status": "invalid", "horizon": f"{horizon}d", "reason": "invalid_close"}

    window = kline[base_idx + 1:target_idx + 1]
    highs = [_to_float(x.get("high") or x.get("close")) for x in window]
    lows = [_to_float(x.get("low") or x.get("close")) for x in window]
    ret_pct = (target_close / base_close - 1) * 100
    max_favorable = ((max(highs) / base_close - 1) * 100) if highs else ret_pct
    max_adverse = ((min(lows) / base_close - 1) * 100) if lows else ret_pct
    return {
        "status": "evaluated",
        "horizon": f"{horizon}d",
        "base_date": _date(base),
        "target_date": _date(target),
        "base_close": round(base_close, 4),
        "target_close": round(target_close, 4),
        "return_pct": round(ret_pct, 2),
        "max_favorable_pct": round(max_favorable, 2),
        "max_adverse_pct": round(max_adverse, 2),
    }


def _failure_reason(kind: str, expected: str, actual_ret: float, hit: bool | None) -> list[str]:
    if hit is not False:
        return []
    reasons: list[str] = []
    if expected in ("up", "buy", "hold", "candidate", "watch_up") and actual_ret < 0:
        reasons.append(f"{kind} 偏多但后验收益为负")
    elif expected in ("down", "reduce", "sell") and actual_ret > 0:
        reasons.append(f"{kind} 偏空/降仓但后验收益为正")
    elif expected in ("neutral", "watch") and abs(actual_ret) >= 1.0:
        reasons.append(f"{kind} 观望但后续波动较大")
    return reasons


def _evaluate_prediction(prediction: dict[str, Any] | None, kline: list[dict[str, Any]], base_idx: int, horizons: tuple[int, ...]) -> dict[str, Any]:
    if not prediction:
        return {"status": "missing", "items": []}
    direction = prediction.get("direction", "neutral")
    items = []
    for horizon in horizons:
        m = _window_metrics(kline, base_idx, horizon)
        if m.get("status") == "evaluated":
            hit = _direction_hit(direction, _to_float(m.get("return_pct")))
            m["hit"] = hit
            m["failure_reasons"] = _failure_reason("预测", direction, _to_float(m.get("return_pct")), hit)
        items.append(m)
    return {
        "status": "ok",
        "trade_date": prediction.get("trade_date"),
        "direction": direction,
        "probability": prediction.get("probability"),
        "confidence": prediction.get("confidence"),
        "items": items,
    }


def _evaluate_selector(selector: dict[str, Any] | None, kline: list[dict[str, Any]], base_idx: int, horizons: tuple[int, ...]) -> dict[str, Any]:
    if not selector:
        return {"status": "missing", "items": []}
    status = selector.get("status", "")
    expected = "candidate" if status == "candidate" else "watch_up" if status == "watch" else "neutral"
    items = []
    for horizon in horizons:
        m = _window_metrics(kline, base_idx, horizon)
        if m.get("status") == "evaluated":
            ret = _to_float(m.get("return_pct"))
            hit = ret >= 0.3 if expected in ("candidate", "watch_up") else None
            m["hit"] = hit
            m["failure_reasons"] = _failure_reason("候选", expected, ret, hit)
        items.append(m)
    return {
        "status": "ok",
        "trade_date": selector.get("trade_date"),
        "selector_status": status,
        "rank_bucket": selector.get("rank_bucket"),
        "upside_score": selector.get("upside_score"),
        "items": items,
    }


def _evaluate_decision(decision: dict[str, Any] | None, kline: list[dict[str, Any]], base_idx: int, horizons: tuple[int, ...]) -> dict[str, Any]:
    if not decision:
        return {"status": "missing", "items": []}
    action = decision.get("action", "watch")
    items = []
    for horizon in horizons:
        m = _window_metrics(kline, base_idx, horizon)
        if m.get("status") == "evaluated":
            ret = _to_float(m.get("return_pct"))
            hit = _decision_hit(action, ret)
            m["hit"] = hit
            m["failure_reasons"] = _failure_reason("决策", action, ret, hit)
        items.append(m)
    return {
        "status": "ok",
        "trade_date": decision.get("trade_date"),
        "action": action,
        "position_suggestion": decision.get("position_suggestion"),
        "confidence": decision.get("confidence"),
        "items": items,
    }


def _summary(sections: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    pending = 0
    failures: list[str] = []
    for section in sections:
        for item in section.get("items") or []:
            if item.get("status") == "evaluated" and item.get("hit") is not None:
                evaluated.append(item)
                failures.extend(item.get("failure_reasons") or [])
            elif item.get("status") == "pending":
                pending += 1
    hit_count = sum(1 for x in evaluated if x.get("hit") is True)
    returns = [_to_float(x.get("return_pct")) for x in evaluated]
    adverse = [_to_float(x.get("max_adverse_pct")) for x in evaluated]
    return {
        "evaluated_count": len(evaluated),
        "pending_count": pending,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / len(evaluated), 4) if evaluated else None,
        "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "worst_adverse_pct": round(min(adverse), 2) if adverse else None,
        "failure_reasons": list(dict.fromkeys(failures)),
    }


def build_review_payload(
    *,
    code: str,
    name: str,
    stock: dict[str, Any] | None,
    prediction: dict[str, Any] | None = None,
    selector: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    stock = stock or {}
    kline = stock.get("kline") or []
    trade_date = (
        (decision or {}).get("trade_date")
        or (selector or {}).get("trade_date")
        or (prediction or {}).get("trade_date")
        or stock.get("trade_date")
        or ""
    )
    base_idx = _find_index(kline, trade_date)
    if base_idx is None:
        return {
            "code": code,
            "name": name or stock.get("name") or code,
            "review_version": REVIEW_VERSION,
            "status": "missing_base_kline",
            "trade_date": trade_date,
            "summary": {"evaluated_count": 0, "pending_count": 0, "hit_rate": None},
            "sections": {},
            "limitations": ["base_trade_date_not_found_in_kline"],
        }

    sections = {
        "prediction": _evaluate_prediction(prediction, kline, base_idx, horizons),
        "selector": _evaluate_selector(selector, kline, base_idx, horizons),
        "decision": _evaluate_decision(decision, kline, base_idx, horizons),
    }
    return {
        "code": code,
        "name": name or stock.get("name") or code,
        "review_version": REVIEW_VERSION,
        "status": "ok",
        "trade_date": trade_date,
        "base_close": _to_float(kline[base_idx].get("close")),
        "sections": sections,
        "summary": _summary(list(sections.values())),
        "limitations": [
            "review_requires_future_kline_after_signal_date",
            "watch_action_hit_rule_uses_abs_return_below_1pct",
        ],
    }
