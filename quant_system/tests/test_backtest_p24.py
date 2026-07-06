"""P2-4 回测增强单元测试。"""

import pandas as pd

from quant_system.backtest.attribution import calc_attribution
from quant_system.backtest.capacity import cap_shares_by_volume
from quant_system.backtest.pool import check_stock_eligible, prepare_backtest_df
from quant_system.backtest.rolling import run_rolling_validation
from quant_system.config.backtest_config import BacktestConfig
from quant_system.strategy.ma_cross import MACrossStrategy


def _trend_df(n: int = 700) -> pd.DataFrame:
    dates = pd.date_range("2022-01-01", periods=n, freq="B")
    closes = [10.0 + i * 0.01 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 0.1 for c in closes],
        "low": [c - 0.1 for c in closes],
        "close": closes,
        "volume": [500000.0] * n,
    })


def test_exclude_st_stock():
    ok, reason = check_stock_eligible("*ST亚士", BacktestConfig())
    assert ok is False
    assert reason == "st_excluded"


def test_capacity_caps_large_order():
    cfg = BacktestConfig(volume_participation_rate=0.05, lot_size=100)
    capped = cap_shares_by_volume(10000, volume=100000, price=10.0, cfg=cfg)
    assert capped <= 5000
    assert capped % 100 == 0


def test_tradable_days_low_liquidity():
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=3, freq="B"),
        "open": [10, 10, 10],
        "high": [10, 10, 10],
        "low": [10, 10, 10],
        "close": [10, 10, 10],
        "volume": [0, 100, 20000000],
    })
    out = prepare_backtest_df(df, BacktestConfig(min_daily_amount_yi=1.0))
    assert out["tradable"].tolist() == [False, False, True]


def test_attribution_groups_by_reason():
    trades = [
        {"date": "2024-01-02", "action": "buy", "status": "filled", "reason": "MA5金叉"},
        {"date": "2024-01-10", "action": "sell", "status": "filled", "reason": "MA20死叉", "pnl": 500},
        {"date": "2024-02-01", "action": "buy", "status": "filled", "reason": "MA5金叉"},
        {"date": "2024-02-08", "action": "sell", "status": "filled", "reason": "MA20死叉", "pnl": -200},
    ]
    eq = [{"date": "2024-01-01", "equity": 100000}, {"date": "2024-02-10", "equity": 100300}]
    attr = calc_attribution(trades, eq)
    assert attr["realized_pnl"] == 300
    assert attr["closed_trades"] == 2
    assert len(attr["by_reason"]) >= 1


def test_rolling_validation_windows():
    df = _trend_df(700)
    cfg = BacktestConfig(
        rolling_train_days=400,
        rolling_test_days=100,
        rolling_step_days=100,
        initial_cash=100_000,
    )
    out = run_rolling_validation(df, MACrossStrategy(), cfg, code="600378")
    assert out["window_count"] >= 1
    assert out["oos_avg_return_pct"] is not None
