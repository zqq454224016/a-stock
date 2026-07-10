"""因子有效性评估。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from quant_system.factors.composite import build_composite_factors
from quant_system.factors.technical import compute_technical_factors
from quant_system.utils.time_utils import now_str

FACTOR_EVAL_VERSION = "1.0.0"
DEFAULT_FACTORS = (
    "technical_score",
    "ma20_bias",
    "rsi14",
    "macd_hist",
    "momentum_20",
    "volume_ratio_20",
    "above_ma20",
)
DEFAULT_HORIZONS = (1, 5, 20)


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / math.sqrt(vx * vy), 4)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
            j += 1
        rank = (i + j + 2) / 2
        for k in range(i, j + 1):
            ranks[order[k][0]] = rank
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _stratified(samples: list[dict[str, Any]], factor: str, horizon: int) -> dict[str, Any]:
    rows = [
        (float(s["factors"][factor]), float(s["returns"][horizon]))
        for s in samples
        if factor in s.get("factors", {}) and horizon in s.get("returns", {})
    ]
    if len(rows) < 6:
        return {"status": "样本不足", "groups": {}}
    rows.sort(key=lambda x: x[0])
    n = len(rows)
    low = rows[: max(1, n // 3)]
    mid = rows[max(1, n // 3): max(2, n * 2 // 3)]
    high = rows[max(2, n * 2 // 3):]
    return {
        "status": "ok",
        "groups": {
            "低分组": {"count": len(low), "avg_return_pct": _avg([x[1] for x in low])},
            "中分组": {"count": len(mid), "avg_return_pct": _avg([x[1] for x in mid])},
            "高分组": {"count": len(high), "avg_return_pct": _avg([x[1] for x in high])},
        },
    }


def _factor_direction(ic: float | None) -> str:
    if ic is None:
        return "样本不足"
    if ic >= 0.05:
        return "正向有效"
    if ic <= -0.05:
        return "反向有效"
    return "弱相关"


def _drift(samples: list[dict[str, Any]], current_factors: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for factor in DEFAULT_FACTORS:
        current = _to_float(current_factors.get(factor))
        history = [
            _to_float(s.get("factors", {}).get(factor))
            for s in samples
            if _to_float(s.get("factors", {}).get(factor)) is not None
        ]
        history = [x for x in history if x is not None]
        if current is None or len(history) < 20:
            out[factor] = {"status": "样本不足", "current": current}
            continue
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std = math.sqrt(variance)
        z = (current - mean) / std if std > 0 else 0.0
        out[factor] = {
            "status": "异常偏高" if z >= 2 else "异常偏低" if z <= -2 else "正常",
            "current": round(current, 4),
            "history_mean": round(mean, 4),
            "zscore": round(z, 4),
        }
    return out


def _stock_samples(stock_payload: dict[str, Any], horizons: tuple[int, ...]) -> list[dict[str, Any]]:
    code = stock_payload.get("code") or ""
    kline = stock_payload.get("kline") or []
    if len(kline) < 80:
        return []
    df = pd.DataFrame(kline)
    samples: list[dict[str, Any]] = []
    max_h = max(horizons)
    for idx in range(60, len(df) - max_h):
        window = df.iloc[: idx + 1].copy()
        current_close = _to_float(window.iloc[-1].get("close"))
        if current_close in (None, 0):
            continue
        technical = compute_technical_factors(window, code, trade_date=str(window.iloc[-1].get("date"))).get("factors") or {}
        composite = build_composite_factors(code, str(window.iloc[-1].get("date")), technical)
        factors = {**technical, "technical_score": composite.get("factors", {}).get("technical_score")}
        factor_values: dict[str, float] = {}
        for factor in DEFAULT_FACTORS:
            value = factors.get(factor)
            if isinstance(value, bool):
                factor_values[factor] = 1.0 if value else 0.0
            elif _to_float(value) is not None:
                factor_values[factor] = float(value)
        returns: dict[int, float] = {}
        for h in horizons:
            future_close = _to_float(df.iloc[idx + h].get("close"))
            if future_close is not None and current_close:
                returns[h] = round((future_close / current_close - 1) * 100, 4)
        if factor_values and returns:
            samples.append({
                "code": code,
                "trade_date": str(window.iloc[-1].get("date")),
                "factors": factor_values,
                "returns": returns,
            })
    return samples


def build_factor_effectiveness_payload(
    *,
    stocks: dict[str, dict[str, Any]],
    current_factors: dict[str, dict[str, Any]] | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """输出技术因子历史有效性评估。"""
    current_factors = current_factors or {}
    samples: list[dict[str, Any]] = []
    for stock in stocks.values():
        samples.extend(_stock_samples(stock, horizons))

    factor_results: dict[str, Any] = {}
    for factor in DEFAULT_FACTORS:
        horizon_results: dict[str, Any] = {}
        for horizon in horizons:
            rows = [
                (float(s["factors"][factor]), float(s["returns"][horizon]))
                for s in samples
                if factor in s.get("factors", {}) and horizon in s.get("returns", {})
            ]
            xs = [x for x, _ in rows]
            ys = [y for _, y in rows]
            ic = _pearson(xs, ys)
            rank_ic = _spearman(xs, ys)
            horizon_results[f"{horizon}d"] = {
                "sample_count": len(rows),
                "ic": ic,
                "rank_ic": rank_ic,
                "direction": _factor_direction(rank_ic if rank_ic is not None else ic),
                "stratified": _stratified(samples, factor, horizon),
            }
        factor_results[factor] = horizon_results

    latest_combined: dict[str, Any] = {}
    for code, payload in current_factors.items():
        for key, value in (payload.get("factors") or {}).items():
            latest_combined.setdefault(key, []).append(value)
    latest_avg = {
        key: _avg([float(v) for v in values if _to_float(v) is not None])
        for key, values in latest_combined.items()
    }

    return {
        "factor_eval_version": FACTOR_EVAL_VERSION,
        "updated_at": now_str(),
        "sample_count": len(samples),
        "stock_count": len(stocks),
        "horizons": [f"{h}d" for h in horizons],
        "factors": factor_results,
        "drift": _drift(samples, latest_avg),
        "limitations": [
            "uses_historical_technical_proxy_samples",
            "pooled_time_series_not_cross_sectional_ic",
            "industry_neutralization_not_applied",
            "sentiment_fundamental_fund_flow_need_point_in_time_history",
        ],
    }
