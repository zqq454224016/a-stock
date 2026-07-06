"""多因子综合策略（技术评分，回测用）。"""

from __future__ import annotations

import pandas as pd

from quant_system.factors.composite import _technical_score
from quant_system.factors.technical import compute_technical_factors
from quant_system.pipeline.adjuster import calc_ma
from quant_system.strategy.base import BaseStrategy

BUY_THRESHOLD = 65
SELL_THRESHOLD = 35


class MultiFactorStrategy(BaseStrategy):
    name = "multi_factor"
    version = "1.0.0"

    def __init__(self, buy_threshold: float = BUY_THRESHOLD, sell_threshold: float = SELL_THRESHOLD):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        work = calc_ma(df.copy())
        scores: list[float] = []

        for i in range(len(work)):
            window = work.iloc[: i + 1]
            payload = compute_technical_factors(window, code="")
            scores.append(_technical_score(payload["factors"]))

        work["factor_score"] = scores
        prev = work["factor_score"].shift(1)

        signal = pd.Series(0, index=work.index, dtype=int)
        buy = (prev < self.buy_threshold) & (work["factor_score"] >= self.buy_threshold)
        sell = (prev > self.sell_threshold) & (work["factor_score"] <= self.sell_threshold)
        signal[buy] = 1
        signal[sell] = -1

        work["signal"] = signal
        work["signal_reason"] = ""
        work.loc[buy, "signal_reason"] = f"因子分突破{self.buy_threshold}"
        work.loc[sell, "signal_reason"] = f"因子分跌破{self.sell_threshold}"
        work["strategy"] = self.name
        return work
