"""回测引擎单元测试。"""

import pandas as pd

from quant_system.backtest.engine import run_backtest
from quant_system.config.backtest_config import BacktestConfig
from quant_system.strategy.ma_cross import MACrossStrategy


def _trend_df(n: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    # 先跌后涨，制造金叉
    closes = [10.0 - i * 0.02 for i in range(n // 2)]
    closes += [closes[-1] + i * 0.05 for i in range(1, n - n // 2 + 1)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c + 0.1 for c in closes],
        "low": [c - 0.1 for c in closes],
        "close": closes,
        "volume": [100000.0] * n,
    })


def test_run_backtest_produces_metrics():
    df = _trend_df()
    result = run_backtest(
        df, MACrossStrategy(), BacktestConfig(initial_cash=100_000),
        code="600378", data_version="test_v1",
    )
    assert result["code"] == "600378"
    assert "metrics" in result
    assert "equity_curve" in result
    assert len(result["equity_curve"]) == len(df)
    m = result["metrics"]
    assert "total_return_pct" in m
    assert "max_drawdown_pct" in m


def test_backtest_reproducible():
    df = _trend_df()
    cfg = BacktestConfig(initial_cash=100_000)
    r1 = run_backtest(df, MACrossStrategy(), cfg, code="600378")
    r2 = run_backtest(df, MACrossStrategy(), cfg, code="600378")
    assert r1["metrics"]["final_equity"] == r2["metrics"]["final_equity"]
    assert len(r1["trades"]) == len(r2["trades"])
