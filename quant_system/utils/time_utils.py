"""时间工具。"""

from __future__ import annotations

from datetime import date, datetime


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def date_slug(d: str | date) -> str:
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    return str(d).replace("-", "")
