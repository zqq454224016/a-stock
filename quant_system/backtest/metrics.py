"""回测绩效指标。"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from quant_system.config.backtest_config import BacktestConfig


def calc_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    cfg: BacktestConfig,
) -> dict[str, Any]:
    if not equity_curve:
        return {}

    eq = pd.DataFrame(equity_curve)
    eq["date"] = pd.to_datetime(eq["date"])
    initial = float(eq["equity"].iloc[0])
    final = float(eq["equity"].iloc[-1])
    total_return = (final / initial - 1) * 100 if initial else 0.0

    days = max(len(eq) - 1, 1)
    years = days / cfg.trading_days_per_year
    annual_return = ((final / initial) ** (1 / years) - 1) * 100 if years > 0 and initial else 0.0

    peak = eq["equity"].cummax()
    dd = (eq["equity"] - peak) / peak
    max_drawdown = round(float(dd.min()) * 100, 2)

    daily_ret = eq["equity"].pct_change().dropna()
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        excess = daily_ret.mean() - cfg.risk_free_rate / cfg.trading_days_per_year
        sharpe = excess / daily_ret.std() * math.sqrt(cfg.trading_days_per_year)
        sharpe = round(float(sharpe), 2)
    else:
        sharpe = None

    closed = [t for t in trades if t.get("action") == "sell" and t.get("pnl") is not None]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] <= 0]
    win_rate = round(len(wins) / len(closed) * 100, 2) if closed else None

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    profit_loss_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else None

    return {
        "total_return_pct": round(total_return, 2),
        "annual_return_pct": round(annual_return, 2),
        "max_drawdown_pct": max_drawdown,
        "sharpe_ratio": sharpe,
        "win_rate_pct": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "trade_count": len(trades),
        "closed_trades": len(closed),
        "final_equity": round(final, 2),
    }
