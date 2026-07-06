"""回测默认配置（Quantification.md §5.4）。"""

from __future__ import annotations

from dataclasses import dataclass

BACKTEST_ENGINE_VERSION = "1.1.0"


@dataclass
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission_rate: float = 0.0003      # 佣金万三
    min_commission: float = 5.0          # 最低 5 元
    stamp_tax_rate: float = 0.001        # 印花税卖出千一
    slippage_bps: float = 5.0            # 滑点 5bp
    limit_pct: float = 0.099             # 涨跌停阈值（主板近似）
    max_position_pct: float = 1.0        # 单票最大仓位（单标的回测默认满仓）
    lot_size: int = 100                  # A 股最小交易单位
    risk_free_rate: float = 0.02         # 夏普计算年化无风险利率
    trading_days_per_year: int = 252
    strategy_version: str = "1.0.0"
    strategy_name: str = "ma_cross"
    # P2-4 可信度增强
    volume_participation_rate: float = 0.05   # 单日最大参与成交量比例
    min_daily_amount_yi: float = 0.05         # 日成交额下限（亿），低于则不可交易
    exclude_st: bool = True
    rolling_enabled: bool = True
    rolling_train_days: int = 504           # 约 2 年 warm-up
    rolling_test_days: int = 126            # 约 6 个月 OOS
    rolling_step_days: int = 126
