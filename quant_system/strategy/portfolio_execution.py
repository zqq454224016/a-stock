"""Deterministic portfolio-level execution and risk accounting for strategy trades."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Cap same-day new entries so rising-regime signal floods cannot fill all slots
# with highly correlated names. Score still ranks within the day.
DEFAULT_MAX_ENTRIES_PER_DAY = 2
ENTRY_SELECTION = "signal_score_desc_daily_cap_code_asc"


def simulate_portfolio(
    trades: pd.DataFrame,
    *,
    initial_cash: float = 50_000.0,
    max_positions: int = 10,
    max_single_weight: float = 0.10,
    max_gross_exposure: float = 0.95,
    max_entries_per_day: int = DEFAULT_MAX_ENTRIES_PER_DAY,
) -> dict[str, Any]:
    required = {"code", "entry_date", "exit_date", "net_return"}
    if trades.empty or not required.issubset(trades.columns):
        return {
            "accepted_trades": 0, "rejected_capacity": 0, "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "max_concurrent_positions": 0,
            "ending_equity": initial_cash, "model": "event_day_marking_v1",
            "entry_selection": ENTRY_SELECTION,
            "limits": {
                "max_positions": max_positions,
                "max_single_weight": max_single_weight,
                "max_gross_exposure": max_gross_exposure,
                "max_entries_per_day": max_entries_per_day,
            },
        }
    events: list[tuple[str, int, float, str, int]] = []
    rows = trades.reset_index(drop=True)
    for index, row in rows.iterrows():
        score = float(row.get("signal_score") or 0.0)
        events.append((str(row["entry_date"])[:10], 1, -score, str(row["code"]), index))
        events.append((str(row["exit_date"])[:10], 0, 0.0, str(row["code"]), index))
    # Exit before entry on the same day so released cash can be reused. Entries
    # compete cross-sectionally by the already-computed deterministic signal
    # score; code and row index are stable tie-breakers.
    events.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))

    cash = float(initial_cash)
    positions: dict[int, float] = {}
    allocations: dict[int, float] = {}
    accepted: set[int] = set()
    rejected_capacity = 0
    rejected_daily_cap = 0
    max_concurrent = 0
    equity_curve: list[float] = [cash]
    entries_on_day = 0
    current_day = ""
    for date, event_type, _score_order, _code, index in events:
        if date != current_day:
            current_day = date
            entries_on_day = 0
        if event_type == 0:
            principal = positions.pop(index, None)
            if principal is not None:
                cash += principal * (1 + float(rows.at[index, "net_return"]))
        else:
            if max_entries_per_day > 0 and entries_on_day >= max_entries_per_day:
                rejected_daily_cap += 1
                rejected_capacity += 1
                continue
            if len(positions) >= max_positions:
                rejected_capacity += 1
                continue
            invested = sum(positions.values())
            equity = cash + invested
            capacity = max(0.0, equity * max_gross_exposure - invested)
            allocation = min(equity * max_single_weight, capacity, cash)
            if allocation <= 0:
                rejected_capacity += 1
                continue
            cash -= allocation
            positions[index] = allocation
            allocations[index] = allocation
            accepted.add(index)
            entries_on_day += 1
            max_concurrent = max(max_concurrent, len(positions))
        equity = cash + sum(positions.values())
        equity_curve.append(equity)

    ending = cash + sum(positions.values())
    daily_curve: list[dict[str, Any]] = []
    max_drawdown = 0.0
    if accepted and "daily_marks" in rows.columns:
        entry_by_date: dict[str, list[int]] = {}
        exit_by_date: dict[str, list[int]] = {}
        mark_by_index: dict[int, dict[str, float]] = {}
        dates: set[str] = set()
        for index in accepted:
            entry = str(rows.at[index, "entry_date"])[:10]
            exit_ = str(rows.at[index, "exit_date"])[:10]
            entry_by_date.setdefault(entry, []).append(index)
            exit_by_date.setdefault(exit_, []).append(index)
            dates.update((entry, exit_))
            marks = {
                str(item.get("date"))[:10]: float(item.get("return") or 0)
                for item in (rows.at[index, "daily_marks"] or [])
                if isinstance(item, dict) and item.get("date")
            }
            mark_by_index[index] = marks
            dates.update(marks)
        daily_cash = float(initial_cash)
        daily_positions: set[int] = set()
        last_mark: dict[int, float] = {}
        peak = initial_cash
        max_drawdown = 0.0
        for day in sorted(dates):
            for index in sorted(exit_by_date.get(day, [])):
                if index in daily_positions:
                    daily_cash += allocations[index] * (1 + float(rows.at[index, "net_return"]))
                    daily_positions.remove(index)
                    last_mark.pop(index, None)
            for index in sorted(entry_by_date.get(day, [])):
                daily_cash -= allocations[index]
                daily_positions.add(index)
            market_value = 0.0
            for index in daily_positions:
                if day in mark_by_index[index]:
                    last_mark[index] = mark_by_index[index][day]
                market_value += allocations[index] * (1 + last_mark.get(index, 0.0))
            daily_equity = daily_cash + market_value
            peak = max(peak, daily_equity)
            max_drawdown = min(max_drawdown, daily_equity / peak - 1)
            daily_curve.append({"date": day, "equity": round(daily_equity, 2)})
    else:
        peak = cash
        max_drawdown = 0.0
        for equity in equity_curve:
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity / peak - 1)
    accepted_returns = rows.loc[sorted(accepted), "net_return"] if accepted else pd.Series(dtype=float)
    return {
        "accepted_trades": len(accepted),
        "rejected_capacity": rejected_capacity,
        "rejected_daily_cap": rejected_daily_cap,
        "acceptance_rate": round(len(accepted) / len(rows), 4) if len(rows) else 0.0,
        "hit_rate": round(float((accepted_returns > 0).mean()), 4) if not accepted_returns.empty else None,
        "total_return_pct": round((ending / initial_cash - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "max_concurrent_positions": max_concurrent,
        "ending_equity": round(ending, 2),
        "limits": {
            "max_positions": max_positions,
            "max_single_weight": max_single_weight,
            "max_gross_exposure": max_gross_exposure,
            "max_entries_per_day": max_entries_per_day,
        },
        "entry_selection": ENTRY_SELECTION,
        "model": "daily_marking_v2" if daily_curve else "event_day_marking_v1",
        "daily_equity_points": len(daily_curve),
        "daily_equity_curve": daily_curve,
        "limitations": ([] if daily_curve else ["输入交易缺少逐日盯市路径"]) + ["行业集中度待行业点时映射"],
    }
