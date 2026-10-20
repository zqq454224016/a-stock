from __future__ import annotations

from datetime import datetime

import pandas as pd

from quant_system.strategy.tail_overnight import (
    SPECS,
    TailSpec,
    gate,
    latest_signals,
    summarize,
    trades,
)
from quant_system.tasks.tail_overnight_recommendation_job import _elapsed_minutes, _timing


def _frame(days: int = 90) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=days)
    rows = []
    price = 10.0
    for index, day in enumerate(dates):
        price *= 1.004
        rows.append({
            "date": day.strftime("%Y-%m-%d"), "open": price * 0.995, "high": price * 1.003,
            "low": price * 0.99, "close": price, "volume": 1000.0, "amount": 2e8,
        })
    # 倒数第二根做成强势收盘：+4%、收在最高、放量
    signal = rows[-2]
    prev_close = rows[-3]["close"]
    signal.update({"open": prev_close, "close": prev_close * 1.04, "high": prev_close * 1.04,
                   "low": prev_close * 0.995, "volume": 2000.0})
    rows[-1].update({"open": signal["close"] * 1.02, "close": signal["close"] * 1.01,
                     "high": signal["close"] * 1.025, "low": signal["close"] * 1.0})
    return pd.DataFrame(rows)


def test_specs_cover_five_modes_with_two_exits() -> None:
    assert len(SPECS) == 10
    assert {spec.exit for spec in SPECS} == {"next_open", "next_close"}


def test_strong_close_enters_at_close_and_exits_next_open_after_costs() -> None:
    frame = _frame()
    spec = TailSpec("t", "strong_close", "next_open", "")
    result = trades(frame, spec, "600001")
    assert len(result) == 1
    row = result.iloc[0]
    assert row.date == frame.iloc[-2]["date"]
    gross = frame.iloc[-1]["open"] / frame.iloc[-2]["close"] - 1
    assert 0 < row.net < gross  # 扣掉佣金、印花税、滑点


def test_limit_up_close_is_not_tradable() -> None:
    frame = _frame()
    prev_close = frame.iloc[-3]["close"]
    frame.loc[len(frame) - 2, ["close", "high"]] = [prev_close * 1.10, prev_close * 1.10]
    assert trades(frame, TailSpec("t", "strong_close", "next_open", ""), "600001").empty


def test_latest_signals_reads_the_synthetic_today_bar() -> None:
    frame = _frame().iloc[:-1]
    hits = latest_signals(frame)
    assert any(hit["mode"] == "strong_close" for hit in hits)


def test_gate_requires_positive_holdout_portfolio() -> None:
    rows = pd.DataFrame({
        "date": [f"2026-01-{d:02d}" for d in range(1, 29)] * 10,
        "code": [f"{i:06d}" for i in range(280)],
        "spec": "t", "net": -0.001, "score": 1.0, "limit_down_exit": False,
    })
    dev = summarize(rows.assign(net=0.002))
    hold = summarize(rows)
    result = gate([dev, dev], hold)
    assert result["dev_passed"] is True
    assert result["diagnostic_passed"] is False
    assert "holdout_portfolio_positive" in result["failed"]


def test_worker_runs_tail_job_once_inside_window(tmp_path, monkeypatch) -> None:
    from quant_system.iteration import worker

    calls = []
    monkeypatch.setattr(worker, "run_tail_overnight_recommendation",
                        lambda cfg, now: calls.append(now) or {"timing": "tail_window", "shadow_recorded": True})

    class Calendar:
        def is_trade_day(self, _):
            return True

    monkeypatch.setattr(worker, "get_calendar", lambda: Calendar())

    class Cfg:
        data_dir = tmp_path

    assert worker._maybe_run_tail_window(Cfg(), datetime(2026, 10, 20, 14, 30)) is None
    status = worker._maybe_run_tail_window(Cfg(), datetime(2026, 10, 20, 14, 48))
    assert status["status"] == "success" and len(calls) == 1
    ledger = tmp_path / "tail_overnight/shadow/2026-10-20.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{}")
    assert worker._maybe_run_tail_window(Cfg(), datetime(2026, 10, 20, 14, 53)) is None
    assert len(calls) == 1


def test_tail_timing_and_volume_scaling() -> None:
    assert _timing(datetime(2026, 10, 19, 14, 48)) == "tail_window"
    assert _timing(datetime(2026, 10, 19, 15, 5)) == "after_close"
    assert _elapsed_minutes(datetime(2026, 10, 19, 14, 48)) == 228
    assert _elapsed_minutes(datetime(2026, 10, 19, 15, 30)) == 240
