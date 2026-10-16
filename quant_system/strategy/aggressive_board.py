"""激进板筛选的日线并行研究代理（与正式推荐门禁对齐，不直接改正式评分）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class AggressiveSpec:
    name: str
    mode: str
    max_hold_days: int = 3  # 对齐激进板 1-5 日持有的中位代理


SPECS = (
    AggressiveSpec("aggressive_breakout_hot", "breakout"),
    AggressiveSpec("aggressive_volume_thrust", "volume_thrust"),
    AggressiveSpec("aggressive_rs_continuation", "rs_continuation"),
)


def _features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    for column in ("open", "high", "low", "close", "volume"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work["ma5"] = work.close.rolling(5).mean()
    work["ma10"] = work.close.rolling(10).mean()
    work["ma20"] = work.close.rolling(20).mean()
    work["vol5"] = work.volume.rolling(5).mean()
    work["vol20"] = work.volume.rolling(20).mean()
    work["day_ret"] = work.close.pct_change()
    work["prior_high_60"] = work.high.rolling(60).max().shift(1)
    work["volume_ratio_5d"] = work.volume / work.vol5.shift(1)
    work["vol_step"] = (
        (work.volume > work.volume.shift(1))
        & (work.volume.shift(1) > work.volume.shift(2))
    )
    work["strong_stack"] = (
        (work.close > work.ma5)
        & (work.ma5 > work.ma10)
        & (work.ma10 > work.ma20)
    )
    return work


def signal_mask(frame: pd.DataFrame, spec: AggressiveSpec) -> pd.Series:
    """日线代理：对齐激进板「强势多头 + 放量/突破/高换手日」核心，不含分时与情绪门。"""
    work = _features(frame)
    hot_day = work.day_ret.between(0.04, 0.095, inclusive="both")
    volume_band = work.volume_ratio_5d.between(1.5, 4.0, inclusive="both")
    common = work.strong_stack & hot_day & volume_band
    if spec.mode == "breakout":
        return common & (work.close > work.prior_high_60) & work.vol_step
    if spec.mode == "volume_thrust":
        return common & work.vol_step & (work.close > work.open) & (work.volume >= work.vol20 * 1.8)
    # rs_continuation: 强势日续涨，不强制破 60 日高
    return common & (work.close > work.open) & (work.volume >= work.vol20 * 1.5)


def backtest(
    frame: pd.DataFrame,
    spec: AggressiveSpec,
    *,
    fee_one_way: float = 0.00008,
    slippage: float = 0.001,
) -> dict[str, Any]:
    work = _features(frame).reset_index(drop=True)
    mask = signal_mask(frame, spec).reset_index(drop=True).fillna(False)
    rows: list[float] = []
    hold = max(1, int(spec.max_hold_days))
    for index in range(len(work) - 1):
        if not bool(mask.iloc[index]):
            continue
        entry = float(work.open.iloc[index + 1])
        exit_at = index + 1 + hold
        if exit_at >= len(work):
            continue
        exit_price = float(work.open.iloc[exit_at])
        net = exit_price / entry - 1 - 2 * fee_one_way - 2 * slippage
        rows.append(net)
    if not rows:
        return {
            "strategy": spec.name,
            "mode": spec.mode,
            "trades": 0,
            "hit_rate": None,
            "avg_net_return_pct": None,
            "proxy": True,
            "max_hold_days": hold,
        }
    series = pd.Series(rows)
    return {
        "strategy": spec.name,
        "mode": spec.mode,
        "trades": len(rows),
        "hit_rate": round(float((series > 0).mean()), 4),
        "avg_net_return_pct": round(float(series.mean() * 100), 4),
        "median_net_return_pct": round(float(series.median() * 100), 4),
        "proxy": True,
        "max_hold_days": hold,
        "limitations": [
            "daily_proxy_omits_intraday_vwap_and_market_sentiment_gate",
            "float_cap_and_turnover_pct_not_in_ohlcv_proxy",
            "does_not_change_formal_aggressive_recommendation",
        ],
    }
