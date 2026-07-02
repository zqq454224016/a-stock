"""风控规则（回测与实盘共用，MVP）。"""

from __future__ import annotations

from quant_system.config.backtest_config import BacktestConfig


def max_shares_for_buy(cash: float, price: float, cfg: BacktestConfig) -> int:
    """按最大仓位计算可买股数（整手）。"""
    if price <= 0:
        return 0
    budget = cash * cfg.max_position_pct
    return int(budget / price // cfg.lot_size) * cfg.lot_size
