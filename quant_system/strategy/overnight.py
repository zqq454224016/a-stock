"""T+1 overnight strategies using daily bars as a conservative research proxy."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd

@dataclass(frozen=True)
class OvernightSpec:
    name: str
    mode: str
    max_hold_days: int = 1

SPECS = (
    OvernightSpec("overnight_close_breakout", "breakout"),
    OvernightSpec("overnight_close_pullback", "pullback"),
    OvernightSpec("overnight_strong_turnover", "turnover"),
)

def _features(frame: pd.DataFrame) -> pd.DataFrame:
    w = frame.copy()
    for c in ("open", "high", "low", "close", "volume"):
        w[c] = pd.to_numeric(w[c], errors="coerce")
    w["ma5"] = w.close.rolling(5).mean()
    w["ma20"] = w.close.rolling(20).mean()
    w["ma60"] = w.close.rolling(60).mean()
    w["vol20"] = w.volume.rolling(20).mean()
    w["range_pos"] = (w.close - w.low) / (w.high - w.low).replace(0, pd.NA)
    w["ret20"] = w.close.pct_change(20)
    return w

def signal_mask(frame: pd.DataFrame, spec: OvernightSpec) -> pd.Series:
    w = _features(frame)
    common = (w.close > w.ma20) & (w.ma20 > w.ma60) & (w.ret20 > 0) & w.range_pos.ge(.7)
    if spec.mode == "breakout":
        return common & (w.close >= w.high.rolling(20).max().shift(1)) & (w.volume >= w.vol20 * 1.2)
    if spec.mode == "pullback":
        return common & (w.low <= w.ma5 * 1.02) & (w.close > w.open) & (w.volume <= w.vol20 * 1.5)
    return common & (w.volume >= w.vol20 * 1.8) & (w.close > w.open)

def backtest(frame: pd.DataFrame, spec: OvernightSpec, *, fee_one_way: float = .00008, slippage: float = .001) -> dict[str, Any]:
    w = _features(frame).reset_index(drop=True)
    mask = signal_mask(frame, spec).reset_index(drop=True).fillna(False)
    rows = []
    for i in range(len(w) - 1):
        if not bool(mask.iloc[i]):
            continue
        entry = float(w.open.iloc[i + 1])
        exit_price = float(w.open.iloc[i + 1])
        # Daily proxy: next-open exit; intraday high/low are diagnostics only.
        if i + 2 < len(w):
            exit_price = float(w.open.iloc[i + 2])
        net = exit_price / entry - 1 - 2 * fee_one_way - 2 * slippage
        rows.append(net)
    if not rows:
        return {"strategy": spec.name, "trades": 0, "hit_rate": None, "avg_net_return_pct": None, "proxy": True}
    s = pd.Series(rows)
    return {"strategy": spec.name, "trades": len(rows), "hit_rate": round(float((s > 0).mean()), 4), "avg_net_return_pct": round(float(s.mean() * 100), 4), "median_net_return_pct": round(float(s.median() * 100), 4), "proxy": True, "limitations": ["daily_bars_cannot_reconstruct_close_auction_or_early_exit", "next_open_slippage_is_conservative_fixed_proxy"]}
