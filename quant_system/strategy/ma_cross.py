"""均线金叉/死叉策略（MA5 × MA20）。"""

from __future__ import annotations

import pandas as pd

from quant_system.pipeline.adjuster import calc_ma
from quant_system.strategy.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
  name = "ma_cross"
  version = "1.0.0"

  def __init__(self, fast: int = 5, slow: int = 20):
    self.fast = fast
    self.slow = slow

  def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
    work = calc_ma(df.copy(), windows=(self.fast, self.slow))
    fast_col = f"ma{self.fast}"
    slow_col = f"ma{self.slow}"

    signal = pd.Series(0, index=work.index, dtype=int)
    prev_fast = work[fast_col].shift(1)
    prev_slow = work[slow_col].shift(1)
    curr_fast = work[fast_col]
    curr_slow = work[slow_col]

    golden = (prev_fast <= prev_slow) & (curr_fast > curr_slow)
    death = (prev_fast >= prev_slow) & (curr_fast < curr_slow)
    signal[golden] = 1
    signal[death] = -1

    work["signal"] = signal
    work["strategy"] = self.name
    return work
