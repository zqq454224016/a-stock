"""模拟交易配置（P3-1）。"""

from __future__ import annotations

from dataclasses import dataclass

SIM_TRADING_VERSION = "1.0.0"


@dataclass
class TradingConfig:
    initial_cash: float = 100_000.0
    max_position_pct: float = 0.20
    min_trade_amount: float = 1_000.0
    min_buy_probability: float = 0.55
    lot_size: int = 100
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.001
    slippage_bps: float = 5.0
