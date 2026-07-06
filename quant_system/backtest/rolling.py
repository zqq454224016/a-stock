"""滚动样本外验证（P2-4）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.backtest.engine import run_backtest
from quant_system.config.backtest_config import BacktestConfig
from quant_system.strategy.base import BaseStrategy


def run_rolling_validation(
    df: pd.DataFrame,
    strategy: BaseStrategy,
    cfg: BacktestConfig,
    *,
    code: str = "",
) -> dict[str, Any]:
    """
    滚动 walk-forward：训练窗仅用于 warm-up，在后续测试窗独立回测。
    规则型策略无参数拟合，测试窗 metrics 视为样本外表现。
    """
    train = cfg.rolling_train_days
    test = cfg.rolling_test_days
    step = cfg.rolling_step_days
    windows: list[dict[str, Any]] = []
    oos_returns: list[float] = []

    i = 0
    while i + train + test <= len(df):
        warm = df.iloc[i: i + train]
        segment = pd.concat([warm.tail(min(60, len(warm))), df.iloc[i + train: i + train + test]])
        segment = segment.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
        if len(segment) < 40:
            break

        res = run_backtest(segment, strategy, cfg, code=code)
        m = res.get("metrics") or {}
        test_start = str(df.iloc[i + train]["date"])[:10]
        test_end = str(df.iloc[i + train + test - 1]["date"])[:10]
        ret = float(m.get("total_return_pct") or 0)
        oos_returns.append(ret)
        windows.append({
            "train_end": str(df.iloc[i + train - 1]["date"])[:10],
            "test_start": test_start,
            "test_end": test_end,
            "total_return_pct": m.get("total_return_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "win_rate_pct": m.get("win_rate_pct"),
            "closed_trades": m.get("closed_trades"),
        })
        i += step

    positive = sum(1 for r in oos_returns if r > 0)
    return {
        "train_days": train,
        "test_days": test,
        "step_days": step,
        "window_count": len(windows),
        "windows": windows,
        "oos_avg_return_pct": round(sum(oos_returns) / len(oos_returns), 2) if oos_returns else None,
        "oos_median_return_pct": round(sorted(oos_returns)[len(oos_returns) // 2], 2) if oos_returns else None,
        "oos_positive_ratio": round(positive / len(oos_returns), 2) if oos_returns else None,
    }
