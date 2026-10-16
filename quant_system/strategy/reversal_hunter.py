"""Deterministic strong-trend bullish reversal strategy.

The strategy deliberately uses only daily bars known at the close.  A signal
created on day T is executed by the backtest engine at the next tradable open,
which avoids look-ahead bias.
"""

from __future__ import annotations

import pandas as pd

from quant_system.strategy.base import BaseStrategy


class ReversalHunterStrategy(BaseStrategy):
    """Find a bullish body reversal after a controlled one-day pullback."""

    name = "reversal_hunter"
    version = "1.0.0"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        close = pd.to_numeric(work["close"], errors="coerce")
        open_ = pd.to_numeric(work["open"], errors="coerce")
        high = pd.to_numeric(work["high"], errors="coerce")
        low = pd.to_numeric(work["low"], errors="coerce")
        volume = pd.to_numeric(work["volume"], errors="coerce")

        ma5 = close.rolling(5, min_periods=5).mean()
        ma10 = close.rolling(10, min_periods=10).mean()
        ma20 = close.rolling(20, min_periods=20).mean()
        high20_before = high.shift(1).rolling(20, min_periods=20).max()
        volume5_before = volume.shift(1).rolling(5, min_periods=5).mean()

        previous_bearish = close.shift(1) < open_.shift(1)
        controlled_pullback = close.shift(1) >= ma10.shift(1) * 0.97
        bullish_reversal = (close > open_) & (close >= open_.shift(1))
        meaningful_body = (close - open_) / open_.where(open_ != 0) >= 0.02
        rising_trend = (ma5 > ma10) & (ma10 > ma20) & (ma20 >= ma20.shift(5))
        near_recent_high = close >= high20_before * 0.94
        adequate_volume = volume >= volume5_before * 0.80

        buy = (
            previous_bearish
            & controlled_pullback
            & bullish_reversal
            & meaningful_body
            & rising_trend
            & near_recent_high
            & adequate_volume
        ).fillna(False)

        # Exits are deterministic trend/structure failures. The engine still
        # enforces T+1 and limit-down execution constraints.
        sell = ((close < ma10) | (close < low.shift(1))).fillna(False)

        signal = pd.Series(0, index=work.index, dtype=int)
        signal.loc[buy] = 1
        signal.loc[sell & ~buy] = -1
        work["signal"] = signal
        work["signal_reason"] = ""
        work.loc[buy, "signal_reason"] = "上升趋势中的阳线反包，收复前一日实体"
        work.loc[sell & ~buy, "signal_reason"] = "跌破10日均线或前一日低点"
        work["reversal_setup"] = buy
        work["strategy"] = self.name
        return work
