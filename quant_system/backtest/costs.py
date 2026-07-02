"""交易成本计算。"""

from __future__ import annotations

from quant_system.config.backtest_config import BacktestConfig


def apply_slippage(price: float, side: str, cfg: BacktestConfig) -> float:
    slip = cfg.slippage_bps / 10_000
    if side == "buy":
        return price * (1 + slip)
    return price * (1 - slip)


def calc_trade_fees(amount: float, side: str, cfg: BacktestConfig) -> float:
    commission = max(amount * cfg.commission_rate, cfg.min_commission)
    stamp = amount * cfg.stamp_tax_rate if side == "sell" else 0.0
    slippage = amount * cfg.slippage_bps / 10_000
    return round(commission + stamp + slippage, 2)
