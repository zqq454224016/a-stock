"""防守/反转 ETF 策略（预登记、参数冻结）。

A 股场内没有反向/杠杆 ETF，下跌市的“反向”动作只能是：减仓到现金、切换到债券/黄金/
红利等防守资产，或在多维超跌条件成立时用宽基 ETF 做反转。所有交易均为 T 日收盘买入、
T+N 日收盘卖出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_system.data_source.etf_history import DEFENSIVE_TYPES, ETF_POOL

ETF_COMMISSION = 0.00008
ETF_SLIPPAGE = 0.0003  # 流动性好的 ETF，单边
CASH_ETF = "511880"
DOWN_REGIMES = ("falling", "extreme_risk")


@dataclass(frozen=True)
class DefensiveSpec:
    name: str
    kind: str          # rotation | reversal | baseline
    hold_days: int
    label: str
    instrument: str = ""   # 反转/基准使用的宽基 ETF
    regime_gate: tuple[str, ...] = ()


SPECS = (
    DefensiveSpec("def_rotation_down", "rotation", 5, "下跌市轮动到最强防守ETF（国债/黄金/红利），否则货币ETF",
                  regime_gate=DOWN_REGIMES),
    DefensiveSpec("def_rotation_always", "rotation", 5, "不看市场状态，始终持有最强防守ETF（对照组）"),
    DefensiveSpec("rev_oversold_hs300_h3", "reversal", 3, "超跌反转条件成立时尾盘买沪深300ETF，持3日", "510300"),
    DefensiveSpec("rev_oversold_hs300_h5", "reversal", 5, "超跌反转条件成立时尾盘买沪深300ETF，持5日", "510300"),
    DefensiveSpec("rev_oversold_cyb_h5", "reversal", 5, "超跌反转条件成立时尾盘买创业板ETF，持5日", "159915"),
    DefensiveSpec("rev_confirmed_hs300_h5", "reversal", 5, "下跌市中沪深300ETF重回MA20且5日收益为正，持5日",
                  "510300", DOWN_REGIMES),
    DefensiveSpec("base_hold_hs300_h5", "baseline", 5, "任意时点买沪深300ETF持5日（基准）", "510300"),
)

# 超跌反转条件（2026-10-19 预登记，回测前冻结）：4 项中至少满足 3 项。
REVERSAL_RULES = {
    "etf_vs_ma20_pct_max": -4.0,     # 价格偏离：ETF 收盘低于 MA20 至少 4%
    "breadth_3d_mean_max": 0.35,     # 抛压持续：近3日平均上涨家数占比 ≤35%
    "amount_ratio_20_min": 1.2,      # 成交放大：全市场成交额 ≥ 20日均额 1.2 倍
    "range_pos_min": 0.5,            # 盘中承接：ETF 收在当日振幅上半部
    "min_conditions": 3,
}


def reversal_setup(etf_row: Any, regime_window: list[dict[str, Any]]) -> dict[str, Any]:
    """多维超跌反转条件；任一项缺数据视为不满足。"""
    rules = REVERSAL_RULES
    close, ma20 = float(etf_row["close"]), etf_row.get("ma20")
    high, low = float(etf_row["high"]), float(etf_row["low"])
    deviation = (close / float(ma20) - 1) * 100 if ma20 is not None and pd.notna(ma20) and ma20 else None
    breadth = [float(r["advance_ratio"]) for r in regime_window[-3:] if r.get("advance_ratio") is not None]
    breadth_3d = sum(breadth) / len(breadth) if len(breadth) == 3 else None
    amount_ratio = regime_window[-1].get("amount_ratio_20") if regime_window else None
    range_pos = (close - low) / (high - low) if high > low else None
    checks = {
        "price_deviation": {"value": round(deviation, 2) if deviation is not None else None,
                            "passed": deviation is not None and deviation <= rules["etf_vs_ma20_pct_max"]},
        "sustained_selling": {"value": round(breadth_3d, 4) if breadth_3d is not None else None,
                              "passed": breadth_3d is not None and breadth_3d <= rules["breadth_3d_mean_max"]},
        "volume_expansion": {"value": round(float(amount_ratio), 3) if amount_ratio is not None else None,
                             "passed": amount_ratio is not None and float(amount_ratio) >= rules["amount_ratio_20_min"]},
        "intraday_support": {"value": round(range_pos, 3) if range_pos is not None else None,
                             "passed": range_pos is not None and range_pos >= rules["range_pos_min"]},
    }
    met = sum(1 for item in checks.values() if item["passed"])
    return {"conditions": checks, "met": met, "passed": met >= rules["min_conditions"]}


def _prep(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["ma20"] = work.close.rolling(20).mean()
    work["ma60"] = work.close.rolling(60).mean()
    work["ret5"] = work.close.pct_change(5)
    work["ret20"] = work.close.pct_change(20)
    return work.set_index("date")


def _cost() -> float:
    return 2 * ETF_COMMISSION + 2 * ETF_SLIPPAGE


def trades(
    spec: DefensiveSpec,
    etfs: dict[str, pd.DataFrame],
    regime_items: list[dict[str, Any]],
) -> pd.DataFrame:
    """返回逐笔交易：date（信号日）、net、instrument、decision_regime。"""
    prepared = {code: _prep(frame) for code, frame in etfs.items() if frame is not None and not frame.empty}
    regimes = sorted((row for row in regime_items if row.get("date")), key=lambda row: row["date"])
    by_date = {str(row["date"]): row for row in regimes}
    calendar = [str(row["date"]) for row in regimes]
    anchor = prepared.get(spec.instrument) if spec.instrument else prepared.get(CASH_ETF)
    if anchor is None:
        return pd.DataFrame(columns=["date", "strategy", "net", "instrument", "decision_regime"])
    calendar_pos = {date: index for index, date in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    next_allowed = ""
    for date in (d for d in anchor.index if d in by_date):
        if date < next_allowed:
            continue
        cal_index = calendar_pos[date]
        prior_regime = by_date[calendar[cal_index - 1]]["regime"] if cal_index > 0 else "unknown"
        today = by_date[date]
        if spec.regime_gate and prior_regime not in spec.regime_gate:
            continue
        instrument = spec.instrument
        if spec.kind == "rotation":
            best, best_ret = None, -np.inf
            for code, meta in ETF_POOL.items():
                if meta["type"] not in DEFENSIVE_TYPES or code not in prepared or date not in prepared[code].index:
                    continue
                row = prepared[code].loc[date]
                if pd.notna(row.ma60) and row.close > row.ma20 >= row.ma60 and row.ret20 > best_ret:
                    best, best_ret = code, row.ret20
            instrument = best or CASH_ETF
        elif spec.kind == "reversal":
            row = anchor.loc[date]
            if spec.regime_gate:
                if not (pd.notna(row.ma20) and row.close > row.ma20 and row.ret5 > 0):
                    continue
            elif not reversal_setup(row, regimes[max(0, cal_index - 2): cal_index + 1])["passed"]:
                continue
        frame = prepared.get(instrument)
        if frame is None or date not in frame.index:
            continue
        loc = frame.index.get_loc(date)
        exit_loc = loc + spec.hold_days
        if exit_loc >= len(frame):
            continue
        entry, exit_price = float(frame.close.iloc[loc]), float(frame.close.iloc[exit_loc])
        rows.append({
            "date": date, "strategy": spec.name, "instrument": instrument,
            "net": exit_price / entry - 1 - _cost(),
            # 超跌反转在尾盘用当日数据决策；其余只用前一交易日状态。
            "decision_regime": today["regime"] if spec.kind == "reversal" and not spec.regime_gate else prior_regime,
        })
        next_allowed = frame.index[exit_loc]
    return pd.DataFrame(rows)
