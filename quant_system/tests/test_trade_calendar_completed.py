from datetime import datetime

from quant_system.utils.trade_calendar import TradeCalendar


class _Calendar(TradeCalendar):
    def fetch_dates(self, force_refresh: bool = False) -> list[str]:
        return ["2026-08-04", "2026-08-05", "2026-08-06"]


def test_latest_completed_trade_day_uses_previous_session_before_close(tmp_path):
    calendar = _Calendar(tmp_path / "calendar.json")

    assert calendar.latest_completed_trade_day(datetime(2026, 8, 6, 9, 0)) == "2026-08-05"
    assert calendar.latest_completed_trade_day(datetime(2026, 8, 6, 15, 1)) == "2026-08-06"
