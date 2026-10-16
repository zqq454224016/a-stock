"""模拟交易配置（P3-1）。"""

from __future__ import annotations

from dataclasses import dataclass

SIM_TRADING_VERSION = "1.2.0"
EXECUTION_SIMULATOR_VERSION = "1.0.0"


@dataclass
class TradingConfig:
    # The paper account mirrors the user-approved capital and fee assumptions.
    initial_cash: float = 50_000.0
    max_position_pct: float = 0.20
    min_trade_amount: float = 1_000.0
    min_buy_probability: float = 0.55
    lot_size: int = 100
    commission_rate: float = 0.00008
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    slippage_bps: float = 5.0
    stop_loss_pct: float = -0.08
    take_profit_pct: float = 0.15
    max_holding_sessions: int = 20
    max_volume_participation_rate: float = 0.01
    limit_threshold_pct: float = 9.8
