"""可验证走势预测（L2：回测证据 + 因子状态）。"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from quant_system.config.factor_config import TECHNICAL_FACTOR_VERSION
from quant_system.config.prediction_config import (
    DEFAULT_HORIZON,
    HORIZON_DAYS,
    MIN_SAMPLES_HIGH,
    MIN_SAMPLES_MEDIUM,
    PREDICTION_VERSION,
)
from quant_system.pipeline.adjuster import calc_ma
from quant_system.utils.time_utils import now_str, today_str


def _confidence(sample_count: int, has_backtest: bool) -> str:
    if not has_backtest or sample_count < MIN_SAMPLES_MEDIUM:
        return "low"
    if sample_count >= MIN_SAMPLES_HIGH:
        return "high"
    return "medium"


def _collect_forward_returns(
    df: pd.DataFrame,
    horizon_days: int,
    state_fn: Callable[[pd.Series], bool],
) -> list[float]:
    work = calc_ma(df.copy())
    samples: list[float] = []
    for i in range(len(work) - horizon_days):
        row = work.iloc[i]
        if not state_fn(row):
            continue
        base = float(row["close"])
        fwd = float(work.iloc[i + horizon_days]["close"])
        if base > 0:
            samples.append((fwd / base) - 1)
    return samples


def _bullish_row(row: pd.Series) -> bool:
    ma5 = row.get("ma5")
    ma20 = row.get("ma20")
    if pd.isna(ma5) or pd.isna(ma20):
        return False
    return float(ma5) > float(ma20) and float(row["close"]) >= float(ma20)


def _bearish_row(row: pd.Series) -> bool:
    ma5 = row.get("ma5")
    ma20 = row.get("ma20")
    if pd.isna(ma5) or pd.isna(ma20):
        return False
    return float(ma5) < float(ma20) and float(row["close"]) < float(ma20)


def _risk_flags(
    factors: dict[str, Any],
    quality: dict[str, Any] | None,
    backtest: dict[str, Any] | None,
    sample_count: int,
    close: float,
) -> list[str]:
    flags: list[str] = []
    if sample_count < MIN_SAMPLES_MEDIUM:
        flags.append("insufficient_samples")
    qscore = (quality or {}).get("quality_score")
    if qscore is not None and qscore < 90:
        flags.append("low_data_quality")
    rsi = factors.get("rsi14")
    if rsi is not None:
        if rsi > 70:
            flags.append("rsi_overbought")
        elif rsi < 30:
            flags.append("rsi_oversold")
    atr = factors.get("atr14")
    if atr and close > 0 and atr / close > 0.05:
        flags.append("high_volatility")
    if backtest:
        m = backtest.get("metrics", {})
        if (m.get("annual_return_pct") or 0) < 0:
            flags.append("strategy_underperform")
        if (m.get("max_drawdown_pct") or 0) < -40:
            flags.append("high_historical_drawdown")
    return flags


def build_verified_prediction(
    code: str,
    df: pd.DataFrame,
    factors: dict[str, Any],
    *,
    backtest: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    horizon: str = DEFAULT_HORIZON,
    data_version: str | None = None,
    trade_date: str | None = None,
    strategy_name: str = "ma_cross",
) -> dict[str, Any]:
    """
    基于历史同类状态的前瞻收益统计 + 回测证据，输出可验证走势预测。
    不输出确定性涨跌结论。
    """
    horizon_days = HORIZON_DAYS.get(horizon, 5)
    td = trade_date or today_str()
    close = float(df.iloc[-1]["close"]) if len(df) else 0.0

    bullish_now = bool(factors.get("above_ma20")) and (factors.get("ma20_bias") or 0) > 0
    bearish_now = not factors.get("above_ma20", True) and (factors.get("ma20_bias") or 0) < 0

    if bullish_now:
        samples = _collect_forward_returns(df, horizon_days, _bullish_row)
        state_label = "bullish"
    elif bearish_now:
        samples = _collect_forward_returns(df, horizon_days, _bearish_row)
        samples = [-r for r in samples]  # 空头视角：下跌为正向
        state_label = "bearish"
    else:
        samples = _collect_forward_returns(df, horizon_days, _bullish_row)
        state_label = "neutral"

    sample_count = len(samples)
    has_backtest = backtest is not None

    if sample_count > 0:
        pos_rate_hist = sum(1 for r in samples if r > 0) / sample_count
        expected_return = round(sum(samples) / sample_count, 4)
        worst = min(samples)
        max_expected_drawdown = round(abs(min(worst, 0)), 4)
    else:
        pos_rate_hist = 0.5
        expected_return = 0.0
        max_expected_drawdown = 0.0

    pos_rate = pos_rate_hist

    # 与回测胜率融合
    if backtest:
        wr = backtest.get("metrics", {}).get("win_rate_pct")
        if wr is not None:
            bt_win = wr / 100.0
            pos_rate = round(pos_rate_hist * 0.6 + bt_win * 0.4, 4)

    if pos_rate >= 0.55:
        direction = "up"
    elif pos_rate <= 0.45:
        direction = "down"
    else:
        direction = "neutral"

    confidence = _confidence(sample_count, has_backtest)

    evidence: dict[str, Any] = {
        "sample_count": sample_count,
        "state_label": state_label,
        "historical_positive_rate": round(pos_rate_hist, 4),
    }
    if backtest:
        m = backtest.get("metrics", {})
        evidence.update({
            "backtest_win_rate": round((m.get("win_rate_pct") or 0) / 100, 4),
            "backtest_profit_loss_ratio": m.get("profit_loss_ratio"),
            "backtest_annual_return_pct": m.get("annual_return_pct"),
            "backtest_max_drawdown_pct": m.get("max_drawdown_pct"),
            "backtest_closed_trades": m.get("closed_trades"),
        })

    risk_flags = _risk_flags(factors, quality, backtest, sample_count, close)

    drivers = []
    if factors.get("above_ma20"):
        drivers.append("站上MA20")
    if factors.get("ma_cross") == "golden":
        drivers.append("均线金叉")
    elif factors.get("ma_cross") == "death":
        drivers.append("均线死叉")
    if factors.get("macd_hist") and factors["macd_hist"] > 0:
        drivers.append("MACD柱为正")

    return {
        "code": code,
        "trade_date": td,
        "horizon": horizon,
        "direction": direction,
        "probability": round(pos_rate, 4),
        "confidence": confidence,
        "expected_return": expected_return,
        "max_expected_drawdown": max_expected_drawdown,
        "prediction_version": PREDICTION_VERSION,
        "strategy": strategy_name,
        "strategy_version": (backtest or {}).get("strategy_version", "1.0.0"),
        "data_version": data_version,
        "factor_versions": {
            "technical": TECHNICAL_FACTOR_VERSION,
        },
        "evidence": evidence,
        "drivers": drivers,
        "risk_flags": risk_flags,
        "disclaimer": "统计倾向，非确定性预测，不构成投资建议",
        "updated_at": now_str(),
    }
