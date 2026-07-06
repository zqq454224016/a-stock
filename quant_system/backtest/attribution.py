"""收益归因（P2-4）。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s[:10], "%Y-%m-%d")


def calc_attribution(trades: list[dict[str, Any]], equity_curve: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t.get("action") == "sell" and t.get("pnl") is not None]
    if not closed:
        return {
            "realized_pnl": 0.0,
            "closed_trades": 0,
            "by_reason": [],
            "avg_hold_days": None,
            "best_trade": None,
            "worst_trade": None,
        }

    buys: dict[str, dict] = {}
    hold_days: list[int] = []
    by_reason: dict[str, list[float]] = defaultdict(list)

    for t in trades:
        if t.get("status") != "filled":
            continue
        if t.get("action") == "buy":
            buys[t["date"]] = t
        elif t.get("action") == "sell" and t.get("pnl") is not None:
            reason = t.get("reason") or "unknown"
            by_reason[reason].append(float(t["pnl"]))
            sell_dt = _parse_date(t["date"])
            buy_dt = None
            for bd in sorted(buys.keys(), reverse=True):
                if bd <= t["date"]:
                    buy_dt = _parse_date(bd)
                    break
            if buy_dt:
                hold_days.append(max((sell_dt - buy_dt).days, 0))

    realized = sum(float(t["pnl"]) for t in closed)
    reason_rows = []
    for reason, pnls in sorted(by_reason.items(), key=lambda x: sum(x[1]), reverse=True):
        wins = [p for p in pnls if p > 0]
        reason_rows.append({
            "reason": reason,
            "count": len(pnls),
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "win_rate_pct": round(len(wins) / len(pnls) * 100, 2),
        })

    best = max(closed, key=lambda t: t["pnl"])
    worst = min(closed, key=lambda t: t["pnl"])

    initial = float(equity_curve[0]["equity"]) if equity_curve else 0
    final = float(equity_curve[-1]["equity"]) if equity_curve else 0

    return {
        "realized_pnl": round(realized, 2),
        "unrealized_hint": round(final - initial - realized, 2),
        "closed_trades": len(closed),
        "avg_hold_days": round(sum(hold_days) / len(hold_days), 1) if hold_days else None,
        "by_reason": reason_rows,
        "best_trade": {
            "date": best.get("date"),
            "pnl": best.get("pnl"),
            "reason": best.get("reason"),
        },
        "worst_trade": {
            "date": worst.get("date"),
            "pnl": worst.get("pnl"),
            "reason": worst.get("reason"),
        },
    }
