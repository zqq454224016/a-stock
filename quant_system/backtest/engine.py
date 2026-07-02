"""日线回测引擎（T+1 + 成本 + 涨跌停）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.backtest.costs import apply_slippage, calc_trade_fees
from quant_system.backtest.metrics import calc_metrics
from quant_system.backtest.rules import is_limit_down, is_limit_up, is_suspended, round_lot
from quant_system.config.backtest_config import BacktestConfig
from quant_system.strategy.base import BaseStrategy
from quant_system.utils.time_utils import now_str


def run_backtest(
    df: pd.DataFrame,
    strategy: BaseStrategy,
    cfg: BacktestConfig | None = None,
    *,
    code: str = "",
    data_version: str | None = None,
    quality_score: float | None = None,
) -> dict[str, Any]:
    """
    回测流程：
    1. 策略在 T 日收盘产生 signal
    2. T+1 日开盘撮合（买入价/卖出价 = 开盘价 + 滑点）
    3. T+1 规则：当日买入不可当日卖出
    """
    cfg = cfg or BacktestConfig()
    work = strategy.generate_signals(df.copy())
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").reset_index(drop=True)

    cash = cfg.initial_cash
    shares = 0
    buy_date: pd.Timestamp | None = None
    buy_cost_basis = 0.0
    pending: str | None = None  # 'buy' | 'sell'
    pending_reason = ""

    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    for i, row in work.iterrows():
        date = row["date"]
        prev_close = float(work.iloc[i - 1]["close"]) if i > 0 else float(row["close"])
        open_price = float(row["open"])
        close_price = float(row["close"])
        suspended = is_suspended(row)

        # 执行昨日信号（今日开盘）
        if pending and not suspended:
            if pending == "buy" and shares == 0:
                if not is_limit_up(open_price, prev_close, cfg):
                    px = apply_slippage(open_price, "buy", cfg)
                    budget = cash * cfg.max_position_pct
                    lot_shares = round_lot(budget / px, cfg.lot_size)
                    if lot_shares >= cfg.lot_size:
                        amount = lot_shares * px
                        fee = calc_trade_fees(amount, "buy", cfg)
                        total = amount + fee
                        if total <= cash:
                            cash -= total
                            shares = lot_shares
                            buy_date = date
                            buy_cost_basis = total
                            trades.append({
                                "date": date.strftime("%Y-%m-%d"),
                                "action": "buy",
                                "price": round(px, 2),
                                "shares": lot_shares,
                                "amount": round(amount, 2),
                                "fee": fee,
                                "reason": pending_reason,
                                "status": "filled",
                            })
                        else:
                            trades.append({
                                "date": date.strftime("%Y-%m-%d"),
                                "action": "buy",
                                "price": round(px, 2),
                                "shares": 0,
                                "reason": pending_reason,
                                "status": "rejected",
                                "reject_reason": "资金不足",
                            })
                else:
                    trades.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "action": "buy",
                        "price": round(open_price, 2),
                        "shares": 0,
                        "reason": pending_reason,
                        "status": "cancelled",
                        "reject_reason": "涨停无法买入",
                    })

            elif pending == "sell" and shares > 0:
                can_sell = buy_date is not None and date > buy_date
                if can_sell:
                    if not is_limit_down(open_price, prev_close, cfg):
                        px = apply_slippage(open_price, "sell", cfg)
                        amount = shares * px
                        fee = calc_trade_fees(amount, "sell", cfg)
                        proceeds = amount - fee
                        pnl = proceeds - buy_cost_basis
                        trades.append({
                            "date": date.strftime("%Y-%m-%d"),
                            "action": "sell",
                            "price": round(px, 2),
                            "shares": shares,
                            "amount": round(amount, 2),
                            "fee": fee,
                            "pnl": round(pnl, 2),
                            "reason": pending_reason,
                            "status": "filled",
                        })
                        cash += proceeds
                        shares = 0
                        buy_date = None
                        buy_cost_basis = 0.0
                    else:
                        trades.append({
                            "date": date.strftime("%Y-%m-%d"),
                            "action": "sell",
                            "price": round(open_price, 2),
                            "shares": shares,
                            "reason": pending_reason,
                            "status": "cancelled",
                            "reject_reason": "跌停无法卖出",
                        })
                else:
                    trades.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "action": "sell",
                        "price": round(open_price, 2),
                        "shares": shares,
                        "reason": pending_reason,
                        "status": "cancelled",
                        "reject_reason": "T+1 当日不可卖",
                    })

        pending = None
        pending_reason = ""

        # 收盘后产生新信号，下一日执行
        sig = int(row.get("signal", 0) or 0)
        if sig == 1 and shares == 0:
            pending = "buy"
            pending_reason = "MA金叉"
        elif sig == -1 and shares > 0:
            pending = "sell"
            pending_reason = "MA死叉"

        equity = cash + shares * close_price
        equity_curve.append({
            "date": date.strftime("%Y-%m-%d"),
            "equity": round(equity, 2),
            "cash": round(cash, 2),
            "shares": shares,
            "close": close_price,
        })

    metrics = calc_metrics(equity_curve, trades, cfg)
    strat = strategy.meta()

    return {
        "code": code,
        "strategy": strat["name"],
        "strategy_version": strat["version"],
        "data_version": data_version,
        "quality_score": quality_score,
        "config": {
            "initial_cash": cfg.initial_cash,
            "commission_rate": cfg.commission_rate,
            "stamp_tax_rate": cfg.stamp_tax_rate,
            "slippage_bps": cfg.slippage_bps,
            "limit_pct": cfg.limit_pct,
        },
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "updated_at": now_str(),
    }
