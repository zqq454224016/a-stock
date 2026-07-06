"""成交量容量约束（P2-4）。"""

from __future__ import annotations

from quant_system.config.backtest_config import BacktestConfig
from quant_system.backtest.rules import round_lot


def cap_shares_by_volume(
    shares: int,
    volume: float,
    price: float,
    cfg: BacktestConfig,
) -> int:
    """限制单笔成交不超过当日成交量的一定比例。"""
    if shares <= 0 or volume <= 0 or price <= 0:
        return shares
    max_amount = volume * price * cfg.volume_participation_rate
    max_shares = int(max_amount / price)
    capped = min(shares, round_lot(max_shares, cfg.lot_size))
    return max(capped, 0)
