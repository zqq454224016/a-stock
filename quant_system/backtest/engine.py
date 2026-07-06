"""日线回测引擎（T+1 + 成本 + 涨跌停 + 容量）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.backtest.attribution import calc_attribution
from quant_system.backtest.capacity import cap_shares_by_volume
from quant_system.backtest.costs import apply_slippage, calc_trade_fees
from quant_system.backtest.metrics import calc_metrics
from quant_system.backtest.pool import prepare_backtest_df
from quant_system.backtest.rules import is_limit_down, is_limit_up, is_suspended, round_lot
from quant_system.config.backtest_config import BACKTEST_ENGINE_VERSION, BacktestConfig
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
    skip_attribution: bool = False,
) -> dict[str, Any]:
    """
    回测流程：
    1. 策略在 T 日收盘产生 signal
    2. T+1 日开盘撮合（买入价/卖出价 = 开盘价 + 滑点）
    3. T+1 规则：当日买入不可当日卖出
    """
    cfg = cfg or BacktestConfig()
    work = prepare_backtest_df(df, cfg)
    work = strategy.generate_signals(work)
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").reset_index(drop=True)

    cash = cfg.initial_cash
    shares = 0
    buy_date: pd.Timestamp | None = None
    buy_cost_basis = 0.0
    pending: str | None = None
    pending_reason = ""

    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    for i, row in work.iterrows():
        date = row["date"]
        prev_close = float(work.iloc[i - 1]["close"]) if i > 0 else float(row["close"])
        open_price = float(row["open"])
        close_price = float(row["close"])
        suspended = is_suspended(row)
        tradable = bool(row.get("tradable", True))

        if pending and not suspended and tradable:
            if pending == "buy" and shares == 0:
                if not is_limit_up(open_price, prev_close, cfg):
                    px = apply_slippage(open_price, "buy", cfg)
                    budget = cash * cfg.max_position_pct
                    lot_shares = round_lot(budget / px, cfg.lot_size)
                    vol = float(row.get("volume", 0) or 0)
                    lot_shares = cap_shares_by_volume(lot_shares, vol, px, cfg)
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
                    elif lot_shares == 0:
                        trades.append({
                            "date": date.strftime("%Y-%m-%d"),
                            "action": "buy",
                            "price": round(px, 2),
                            "shares": 0,
                            "reason": pending_reason,
                            "status": "cancelled",
                            "reject_reason": "成交量容量不足",
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
                        sell_shares = shares
                        vol = float(row.get("volume", 0) or 0)
                        sell_shares = cap_shares_by_volume(sell_shares, vol, px, cfg)
                        if sell_shares < cfg.lot_size:
                            trades.append({
                                "date": date.strftime("%Y-%m-%d"),
                                "action": "sell",
                                "price": round(px, 2),
                                "shares": shares,
                                "reason": pending_reason,
                                "status": "cancelled",
                                "reject_reason": "成交量容量不足",
                            })
                        else:
                            amount = sell_shares * px
                            fee = calc_trade_fees(amount, "sell", cfg)
                            proceeds = amount - fee
                            sold_ratio = sell_shares / shares
                            pnl = proceeds - buy_cost_basis * sold_ratio
                            trades.append({
                                "date": date.strftime("%Y-%m-%d"),
                                "action": "sell",
                                "price": round(px, 2),
                                "shares": sell_shares,
                                "amount": round(amount, 2),
                                "fee": fee,
                                "pnl": round(pnl, 2),
                                "reason": pending_reason,
                                "status": "filled",
                            })
                            cash += proceeds
                            if sell_shares >= shares:
                                shares = 0
                                buy_date = None
                                buy_cost_basis = 0.0
                            else:
                                shares -= sell_shares
                                buy_cost_basis *= (1 - sold_ratio)
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
        elif pending and not tradable:
            trades.append({
                "date": date.strftime("%Y-%m-%d"),
                "action": pending,
                "price": round(open_price, 2),
                "shares": 0,
                "reason": pending_reason,
                "status": "cancelled",
                "reject_reason": "流动性不足",
            })

        pending = None
        pending_reason = ""

        sig = int(row.get("signal", 0) or 0)
        if sig == 1 and shares == 0:
            pending = "buy"
            pending_reason = str(row.get("signal_reason") or "买入信号")
        elif sig == -1 and shares > 0:
            pending = "sell"
            pending_reason = str(row.get("signal_reason") or "卖出信号")

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
    attribution = {} if skip_attribution else calc_attribution(trades, equity_curve)

    return {
        "code": code,
        "strategy": strat["name"],
        "strategy_version": strat["version"],
        "engine_version": BACKTEST_ENGINE_VERSION,
        "data_version": data_version,
        "quality_score": quality_score,
        "config": {
            "initial_cash": cfg.initial_cash,
            "commission_rate": cfg.commission_rate,
            "stamp_tax_rate": cfg.stamp_tax_rate,
            "slippage_bps": cfg.slippage_bps,
            "limit_pct": cfg.limit_pct,
            "volume_participation_rate": cfg.volume_participation_rate,
            "min_daily_amount_yi": cfg.min_daily_amount_yi,
        },
        "metrics": metrics,
        "attribution": attribution,
        "equity_curve": equity_curve,
        "trades": trades,
        "updated_at": now_str(),
    }
