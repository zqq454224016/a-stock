"""「尾盘板块T+1观察」规则的历史回放。

原样复现 recommendation/builder.py 中 _tail_sector_filter 的实际行为：
板块只在当日涨幅前5/后5中匹配（builder 的 sector_changes 只含领涨/领跌各5个），
所以“所属板块上涨”等价于所属行业进入当日涨幅前5且为正。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_system.strategy.robust_iteration import TRANSACTION_FEE_RATE, slippage_rate
from quant_system.strategy.tail_overnight import LIMIT_MOVE, MAX_EXIT_GAP_DAYS, STAMP_TAX_RATE

SECTOR_TOP_N = 5
EXITS = (("tail_sector_next_open", "next_open"), ("tail_sector_next_close", "next_close"))


def sector_board(data_dir: Path) -> dict[str, dict[str, float]]:
    """每个交易日的领涨前5与领跌后5行业涨跌幅（%）。"""
    changes: dict[str, dict[str, float]] = {}
    for path in sorted((data_dir / "sector_data" / "history").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = payload.get("industry") or path.stem
        rows = payload.get("rows") or []
        previous = None
        for row in rows:
            close = float(row.get("close") or 0)
            if previous and close > 0:
                changes.setdefault(str(row["date"])[:10], {})[name] = (close / previous - 1) * 100
            previous = close if close > 0 else previous
    board: dict[str, dict[str, float]] = {}
    for date, values in changes.items():
        ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
        picked = ordered[:SECTOR_TOP_N] + ordered[-SECTOR_TOP_N:]
        board[date] = dict(picked)
    return board


def industry_map(data_dir: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads((data_dir / "sector_data/stock_industry_map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {code: list(item.get("industries") or []) for code, item in (payload.get("stocks") or {}).items()}


def benchmark_returns(etf_frame: pd.DataFrame | None) -> dict[str, float]:
    if etf_frame is None or etf_frame.empty:
        return {}
    closes = etf_frame.set_index("date").close
    return {str(d): float(v) * 100 for d, v in closes.pct_change().dropna().items()}


def trades(
    frame: pd.DataFrame,
    code: str,
    industries: list[str],
    board: dict[str, dict[str, float]],
    bench: dict[str, float],
) -> pd.DataFrame:
    work = frame.copy()
    for column in ("open", "high", "low", "close", "amount"):
        work[column] = pd.to_numeric(work.get(column), errors="coerce")
    work["date"] = work["date"].astype(str).str[:10]
    work["change"] = (work.close / work.close.shift(1) - 1) * 100
    work["ma5"] = work.close.rolling(5).mean()
    work["ma20"] = work.close.rolling(20).mean()
    base = (
        work.change.between(0.5, 8.0) & (work.close > work.ma20) & (work.ma5 >= work.ma20)
        & (work.change < LIMIT_MOVE * 100) & (work.high > work.low)
    ).fillna(False).to_numpy()
    dates = work.date.to_numpy()
    rows = []
    for index in np.flatnonzero(base):
        if index + 1 >= len(work):
            continue
        date = dates[index]
        if date not in bench or work.change.iat[index] - bench[date] < 0:
            continue
        top = board.get(date) or {}
        matched = next((name for name in reversed(industries) if name in top), None)
        if matched is None or not top[matched] > 0:
            continue
        gap = (pd.Timestamp(dates[index + 1]) - pd.Timestamp(date)).days
        if gap > MAX_EXIT_GAP_DAYS:
            continue
        close = work.close.iat[index]
        nxt_open, nxt_close = work.open.iat[index + 1], work.close.iat[index + 1]
        slip = slippage_rate(work.amount.iat[index])
        for name, exit_kind in EXITS:
            price = nxt_open if exit_kind == "next_open" else nxt_close
            if nxt_open / close - 1 <= -LIMIT_MOVE:
                price = min(nxt_open, nxt_close)
            net = price * (1 - slip) / (close * (1 + slip)) - 1 - 2 * TRANSACTION_FEE_RATE - STAMP_TAX_RATE
            rows.append({"date": date, "code": code, "spec": name, "net": float(net),
                         "score": float(work.change.iat[index] - bench[date]), "limit_down_exit": False,
                         "sector": matched})
    return pd.DataFrame(rows)


def load_context(data_dir: Path) -> dict[str, Any]:
    from quant_system.data_source.etf_history import load_etf_history

    return {
        "board": sector_board(data_dir),
        "industries": industry_map(data_dir),
        "bench": benchmark_returns(load_etf_history(data_dir, "510300")),
    }
