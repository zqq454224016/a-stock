"""A 股交易时段判断。"""

from __future__ import annotations

from datetime import datetime, time

from quant_system.utils.trade_calendar import get_calendar


def _now() -> datetime:
    return datetime.now()


def is_trade_day(d: datetime | None = None) -> bool:
    d = d or _now()
    try:
        return get_calendar().is_trade_day(d.date())
    except Exception:
        return d.weekday() < 5


def is_market_open(now: datetime | None = None) -> bool:
    """粗略判断是否在 A 股连续竞价时段（9:30-11:30, 13:00-15:00）。"""
    now = now or _now()
    if not is_trade_day(now):
        return False
    t = now.time()
    morning = time(9, 30) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def market_session_label(now: datetime | None = None) -> str:
    now = now or _now()
    if not is_trade_day(now):
        return "closed_holiday"
    t = now.time()
    if t < time(9, 30):
        return "pre_market"
    if time(9, 30) <= t <= time(11, 30):
        return "morning"
    if time(11, 30) < t < time(13, 0):
        return "lunch_break"
    if time(13, 0) <= t <= time(15, 0):
        return "afternoon"
    return "after_hours"
