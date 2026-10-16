"""Deterministic multi-horizon trend-development research strategy."""

from __future__ import annotations

from typing import Any

import pandas as pd

STRATEGY_NAME = "trend_development"
STRATEGY_VERSION = "1.0.0"


def _series(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for key in ("close", "volume"):
        work[key] = pd.to_numeric(work.get(key), errors="coerce")
    close = work["close"]
    work["ma20"] = close.rolling(20).mean()
    work["ma60"] = close.rolling(60).mean()
    work["momentum20"] = close.pct_change(20) * 100
    work["momentum60"] = close.pct_change(60) * 100
    work["ma20_slope10"] = work["ma20"].pct_change(10) * 100
    work["volatility20"] = close.pct_change().rolling(20).std() * (252 ** 0.5) * 100
    score = (
        50 + work["momentum20"].fillna(0) * 1.2 + work["momentum60"].fillna(0) * 0.35
        + work["ma20_slope10"].fillna(0) * 2
        + (close > work["ma20"]).astype(float) * 6 - (close <= work["ma20"]).astype(float) * 6
        + (work["ma20"] > work["ma60"]).astype(float) * 8 - (work["ma20"] <= work["ma60"]).astype(float) * 8
    )
    work["trend_score"] = score.clip(0, 100)
    work["trend_stage"] = "weakening"
    work.loc[(work["trend_score"] >= 65) & (work["ma20"] > work["ma60"]), "trend_stage"] = "rising"
    work.loc[(work["trend_score"] <= 35) & (work["ma20"] <= work["ma60"]), "trend_stage"] = "falling"
    work.loc[(work["trend_score"] > 50) & (close > work["ma20"]) & (work["ma20"] <= work["ma60"]), "trend_stage"] = "recovery"
    return work


def analyze_trend_development(df: pd.DataFrame, code: str, name: str = "") -> dict[str, Any]:
    if len(df) < 60:
        return {"code": code, "name": name, "strategy": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION, "status": "insufficient", "limitations": ["history_less_than_60_bars"]}
    work = _series(df)
    row = work.iloc[-1]
    score = round(float(row["trend_score"]), 2)
    stage = str(row["trend_stage"])
    confidence = "high" if score >= 75 or score <= 25 else "medium" if score >= 62 or score <= 38 else "low"
    direction = "up" if stage in {"rising", "recovery"} else "down" if stage == "falling" else "neutral"
    date_value = row.get("date") or row.get("trade_date")
    trade_date = date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else str(date_value)[:10]
    return {
        "code": code, "name": name, "trade_date": trade_date,
        "strategy": STRATEGY_NAME, "strategy_version": STRATEGY_VERSION, "status": "analyzed",
        "trend_stage": stage, "trend_score": score, "confidence": confidence,
        "outlook": {horizon: {"direction": direction, "strength": confidence} for horizon in ("5d", "20d", "60d")},
        "metrics": {key: round(float(row[key]), 4) if pd.notna(row[key]) else None for key in ("ma20", "ma60", "momentum20", "momentum60", "ma20_slope10", "volatility20")},
        "manual_review": {"required": True, "status": "pending", "checks": ["最新公告和中报", "停牌/ST/涨跌停", "市场情绪与行业共振", "流动性和交易成本"]},
        "limitations": ["rule_based_trend_not_return_guarantee", "manual_confirmation_required"],
    }


def evaluate_history(df: pd.DataFrame, *, window_days: int = 1250) -> dict[str, Any]:
    """Vectorized walk-forward-style evaluation over the requested history."""
    available_window = min(max(0, len(df) - 60), window_days)
    work = _series(df).tail(available_window + 60).copy()
    evaluated = work.iloc[-available_window:].copy()
    output: dict[str, Any] = {}
    for horizon in (5, 20, 60):
        future_return = work["close"].shift(-horizon) / work["close"] - 1
        evaluated_return = future_return.reindex(evaluated.index)
        predicted = evaluated["trend_stage"].map({"rising": 1, "recovery": 1, "falling": -1, "weakening": 0})
        mask = predicted.ne(0) & evaluated_return.notna()
        signed = evaluated_return[mask] * predicted[mask]
        output[f"{horizon}d"] = {
            "sample_count": int(mask.sum()),
            "hit_rate": round(float((signed > 0).mean()), 4) if mask.any() else None,
            "avg_signed_return_pct": round(float(signed.mean() * 100), 3) if mask.any() else None,
            "max_adverse_pct": round(float(signed.min() * 100), 3) if mask.any() else None,
        }
    return {
        "window": f"past_{available_window}_trading_days",
        "requested_window_days": window_days,
        "evaluated_window_days": available_window,
        "metrics": output,
        "limitations": ["listing_history_shorter_than_requested_window"] if available_window < window_days else [],
    }


def evaluate_one_year(df: pd.DataFrame) -> dict[str, Any]:
    """Compatibility wrapper for callers that explicitly request one year."""
    return evaluate_history(df, window_days=252)
