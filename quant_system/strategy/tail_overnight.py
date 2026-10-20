"""尾盘进、次日出：收盘集合竞价买入，次日开盘或收盘卖出的日线研究模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_system.strategy.robust_iteration import TRANSACTION_FEE_RATE, slippage_rate

STAMP_TAX_RATE = 0.0005  # 卖出单边
LIMIT_MOVE = 0.095       # 主板涨跌停代理；研究宇宙已排除创业板/科创板/北交所
MAX_EXIT_GAP_DAYS = 7    # 次日K线间隔过长视为停牌，无法按计划卖出

DAILY_TOP_K = 5
HOLDOUT_TRADE_DAYS = 60
TAIL_SOURCE_ID = "tail_overnight_v1_20261019"


@dataclass(frozen=True)
class TailSpec:
    name: str
    mode: str
    exit: str  # next_open | next_close
    label: str


_MODES = (
    ("strong_close", "强势收盘：温和涨幅、收在高位、放量、趋势向上"),
    ("breakout", "收盘突破20日高点并放量"),
    ("pullback", "上升趋势回踩10日线后收稳"),
    ("quiet_up", "低波动温和上涨、收在高位"),
    ("reversal", "放量下跌后收长下影"),
)
_EXITS = (("next_open", "次日开盘卖"), ("next_close", "次日收盘卖"))

SPECS = tuple(
    TailSpec(f"tail_{mode}_{exit_key}", mode, exit_key, f"{label}；{exit_label}")
    for mode, label in _MODES
    for exit_key, exit_label in _EXITS
)


def features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        work[column] = pd.to_numeric(work.get(column), errors="coerce")
    work["prev_close"] = work.close.shift(1)
    work["ret"] = work.close / work.prev_close - 1
    span = (work.high - work.low).replace(0, np.nan)
    work["range_pos"] = (work.close - work.low) / span
    work["upper_shadow"] = (work.high - work.close) / work.close
    work["vol_ratio"] = work.volume / work.volume.shift(1).rolling(5).mean()
    for n in (5, 10, 20, 60):
        work[f"ma{n}"] = work.close.rolling(n).mean()
    work["high20_prior"] = work.high.shift(1).rolling(20).max()
    work["volatility20"] = work.ret.rolling(20).std()
    work["limit_up_close"] = work.ret >= LIMIT_MOVE
    work["one_price"] = work.high <= work.low
    return work


def signal_mask(work: pd.DataFrame, mode: str) -> pd.Series:
    tradable = ~work.limit_up_close & ~work.one_price & work.ma60.notna()
    if mode == "strong_close":
        cond = (
            work.ret.between(0.02, 0.07) & work.range_pos.ge(0.8)
            & work.vol_ratio.between(1.2, 3.0) & (work.close > work.ma20)
            & (work.ma20 > work.ma60) & work.upper_shadow.le(0.01)
        )
    elif mode == "breakout":
        cond = (
            (work.close > work.high20_prior) & work.ret.between(0.02, 0.08)
            & work.vol_ratio.ge(1.5) & work.range_pos.ge(0.7)
        )
    elif mode == "pullback":
        cond = (
            (work.ma20 > work.ma60) & (work.close > work.ma20)
            & (work.low <= work.ma10 * 1.01) & work.ret.between(-0.01, 0.03)
            & work.range_pos.ge(0.6) & work.vol_ratio.le(1.2)
        )
    elif mode == "quiet_up":
        cond = (
            work.volatility20.le(0.02) & work.ret.between(0.01, 0.04)
            & work.range_pos.ge(0.75) & (work.close > work.ma20)
        )
    elif mode == "reversal":
        cond = (
            work.ret.between(-0.07, -0.03) & work.range_pos.ge(0.6)
            & work.vol_ratio.ge(1.2)
        )
    else:
        raise ValueError(f"unknown tail mode: {mode}")
    return (tradable & cond).fillna(False)


def signal_score(work: pd.DataFrame, mode: str) -> pd.Series:
    """同日横截面排序用；越大越优先。"""
    if mode == "strong_close":
        return work.ret + 0.02 * work.range_pos
    if mode == "breakout":
        return work.close / work.high20_prior - 1 + 0.01 * work.vol_ratio.clip(upper=4)
    if mode == "pullback":
        return work.range_pos - (work.close / work.ma10 - 1).abs()
    if mode == "quiet_up":
        return work.ret / work.volatility20.replace(0, np.nan)
    return work.range_pos - work.ret


def _slippage(amount: pd.Series) -> pd.Series:
    return amount.map(slippage_rate)


def trades(frame: pd.DataFrame, spec: TailSpec, code: str = "") -> pd.DataFrame:
    """每个信号日一笔：T 日收盘价买入，T+1 按出场方式卖出。"""
    work = features(frame).reset_index(drop=True)
    work["date"] = pd.to_datetime(work["date"].astype(str).str[:10], errors="coerce")
    mask = signal_mask(work, spec.mode)
    nxt_date = work.date.shift(-1)
    nxt_open, nxt_close = work.open.shift(-1), work.close.shift(-1)
    gap = (nxt_date - work.date).dt.days
    valid = mask & nxt_close.notna() & gap.le(MAX_EXIT_GAP_DAYS)
    if not valid.any():
        return pd.DataFrame(columns=["date", "code", "spec", "net", "score", "limit_down_exit"])
    rows = work[valid]
    planned = (nxt_open if spec.exit == "next_open" else nxt_close)[valid]
    open_limit_down = (nxt_open[valid] / rows.close - 1) <= -LIMIT_MOVE
    # 开盘一字跌停无法按计划卖出：保守取开盘与收盘中的更差价。
    exit_price = np.where(open_limit_down, np.minimum(nxt_open[valid], nxt_close[valid]), planned)
    slip = _slippage(rows.amount)
    entry = rows.close * (1 + slip)
    exit_net = exit_price * (1 - slip)
    net = exit_net / entry - 1 - 2 * TRANSACTION_FEE_RATE - STAMP_TAX_RATE
    return pd.DataFrame({
        "date": rows.date.dt.strftime("%Y-%m-%d").values,
        "code": code,
        "spec": spec.name,
        "net": net.astype(float).values,
        "score": signal_score(work, spec.mode)[valid].astype(float).values,
        "limit_down_exit": open_limit_down.values,
    })


def latest_signals(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """对最后一根（盘中合成）K线判断各策略是否触发。"""
    work = features(frame).reset_index(drop=True)
    if work.empty:
        return []
    last = len(work) - 1
    hits = []
    for spec in SPECS:
        if not bool(signal_mask(work, spec.mode).iloc[last]):
            continue
        row = work.iloc[last]
        hits.append({
            "spec": spec.name,
            "mode": spec.mode,
            "exit": spec.exit,
            "score": float(signal_score(work, spec.mode).iloc[last]),
            "ret_pct": round(float(row.ret) * 100, 2),
            "range_pos": round(float(row.range_pos), 3) if pd.notna(row.range_pos) else None,
            "vol_ratio": round(float(row.vol_ratio), 2) if pd.notna(row.vol_ratio) else None,
            "close": float(row.close),
            "ma20": round(float(row.ma20), 3) if pd.notna(row.ma20) else None,
        })
    return hits


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(((equity / peak) - 1).min() * 100)


def summarize(rows: pd.DataFrame, *, top_k: int = DAILY_TOP_K) -> dict[str, Any]:
    if rows.empty:
        return {"trades": 0, "hit_rate": None, "avg_net_return_pct": None,
                "median_net_return_pct": None, "portfolio": {"days": 0}}
    net = rows.net
    picked = (
        rows.sort_values(["date", "score", "code"], ascending=[True, False, True])
        .groupby("date", sort=True).head(top_k)
    )
    daily = picked.groupby("date").net.sum() / top_k
    equity = np.cumprod(1 + daily.values)
    return {
        "trades": int(len(rows)),
        "hit_rate": round(float((net > 0).mean()), 4),
        "avg_net_return_pct": round(float(net.mean() * 100), 4),
        "median_net_return_pct": round(float(net.median() * 100), 4),
        "limit_down_exit_count": int(rows.limit_down_exit.sum()),
        "portfolio": {
            "top_k_per_day": top_k,
            "days": int(len(daily)),
            "day_hit_rate": round(float((daily > 0).mean()), 4),
            "avg_daily_return_pct": round(float(daily.mean() * 100), 4),
            "total_return_pct": round(float((equity[-1] - 1) * 100), 2),
            "max_drawdown_pct": round(_max_drawdown(equity), 2),
        },
    }


GATE = {
    "dev_segment_min_trades": 200,
    "holdout_min_trades": 100,
    "holdout_min_hit_rate": 0.50,
    "holdout_min_portfolio_days": 30,
    "holdout_max_drawdown_pct": -15.0,
}


def gate(dev_segments: list[dict[str, Any]], holdout: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for index, seg in enumerate(dev_segments):
        port = seg.get("portfolio") or {}
        checks += [
            {"id": f"dev{index}_trades", "passed": seg.get("trades", 0) >= GATE["dev_segment_min_trades"]},
            {"id": f"dev{index}_avg_net_positive", "passed": (seg.get("avg_net_return_pct") or -99) > 0},
            {"id": f"dev{index}_portfolio_positive", "passed": (port.get("total_return_pct") or -99) > 0},
        ]
    hport = holdout.get("portfolio") or {}
    checks += [
        {"id": "holdout_trades", "passed": holdout.get("trades", 0) >= GATE["holdout_min_trades"]},
        {"id": "holdout_avg_net_positive", "passed": (holdout.get("avg_net_return_pct") or -99) > 0},
        {"id": "holdout_hit_rate", "passed": (holdout.get("hit_rate") or 0) >= GATE["holdout_min_hit_rate"]},
        {"id": "holdout_portfolio_positive", "passed": (hport.get("total_return_pct") or -99) > 0},
        {"id": "holdout_portfolio_days", "passed": hport.get("days", 0) >= GATE["holdout_min_portfolio_days"]},
        {"id": "holdout_drawdown", "passed": (hport.get("max_drawdown_pct") or -100) >= GATE["holdout_max_drawdown_pct"]},
    ]
    dev_ok = all(c["passed"] for c in checks if c["id"].startswith("dev"))
    return {
        "dev_passed": dev_ok,
        "diagnostic_passed": all(c["passed"] for c in checks),
        "failed": [c["id"] for c in checks if not c["passed"]],
    }
