from __future__ import annotations

import pandas as pd

from quant_system.strategy.defensive_etf import SPECS as DEFENSIVE_SPECS
from quant_system.strategy.defensive_etf import trades as defensive_trades
from quant_system.strategy.track_catalog import (
    TRACK_DEFENSIVE,
    TRACK_LONG,
    TRACK_SHORT,
    TRACK_ULTRA,
    build_catalog,
    track_for_hold_days,
)
from quant_system.tasks.strategy_track_evidence_job import _cell, _evaluate


def test_track_assignment_uses_holding_days_only() -> None:
    assert track_for_hold_days(1) == TRACK_ULTRA
    assert track_for_hold_days(2) == TRACK_ULTRA
    assert track_for_hold_days(5) == TRACK_SHORT
    assert track_for_hold_days(10) == TRACK_SHORT
    assert track_for_hold_days(20) == TRACK_LONG


def test_catalog_covers_every_parallel_stream_once() -> None:
    entries = build_catalog()
    names = [entry.name for entry in entries]
    assert len(names) == len(set(names))
    tracks = {entry.track for entry in entries}
    assert tracks == {TRACK_LONG, TRACK_SHORT, TRACK_ULTRA, TRACK_DEFENSIVE}
    assert all(entry.track == TRACK_ULTRA for entry in entries if entry.source == "tail")


def _etf(prices: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(prices)).strftime("%Y-%m-%d")
    return pd.DataFrame({"date": dates, "open": prices, "high": prices, "low": prices, "close": prices,
                         "volume": 1.0, "amount": 1e9})


def test_oversold_reversal_needs_three_of_four_conditions() -> None:
    prices = [10.0] * 80 + [9.0, 9.2, 9.4, 9.6, 9.8, 10.0, 10.0]
    etf = _etf(prices)
    etf.loc[80, ["high", "low"]] = [9.1, 8.8]  # 收在振幅上半部：盘中承接
    items = [{"date": d, "regime": "falling", "advance_ratio": 0.5, "amount_ratio_20": 1.0} for d in etf.date]
    for index in (78, 79, 80):
        items[index]["advance_ratio"] = 0.30  # 近3日抛压持续
    spec = next(s for s in DEFENSIVE_SPECS if s.name == "rev_oversold_hs300_h5")
    # 价格偏离（-10%）+ 抛压持续 + 盘中承接 = 3 项，成交未放大
    result = defensive_trades(spec, {"510300": etf}, items)
    assert len(result) == 1
    assert result.iloc[0]["date"] == etf.date[80]
    assert abs(result.iloc[0]["net"] - (10.0 / 9.0 - 1 - 0.00076)) < 1e-6
    # 单日家数极低但其余条件都不满足时不触发
    items = [{"date": d, "regime": "falling", "advance_ratio": 0.5, "amount_ratio_20": 1.0} for d in etf.date]
    items[80]["advance_ratio"] = 0.05
    flat = _etf([10.0] * 87)
    assert defensive_trades(spec, {"510300": flat}, items).empty


def test_regime_cell_requires_both_development_halves_positive() -> None:
    calendar = list(pd.bdate_range("2020-01-01", periods=400).strftime("%Y-%m-%d"))
    dates = [int(d.replace("-", "")) for d in calendar[:300]]
    nets = [0.01 if i < 150 else -0.002 for i in range(300)]
    rows = pd.DataFrame({
        "strategy": pd.Categorical(["tail_quiet_up_next_close"] * 300),
        "date": dates, "net": nets,
        "decision_regime": pd.Categorical(["range"] * 300),
    })
    catalog = {entry.name: entry for entry in build_catalog()}
    result = _evaluate(rows, catalog, calendar)
    cell = result["tail_quiet_up_next_close"]["by_regime"]["range"]
    assert cell["development"]["avg_net_return_pct"] > 0
    assert cell["evidence_passed"] is False  # 后半段为负


def test_walkforward_only_uses_purged_prior_years() -> None:
    from quant_system.tasks.long_walkforward_job import walkforward

    days = pd.bdate_range("2016-01-04", "2020-12-31")
    rows = pd.DataFrame({
        "strategy": "cand",
        "date": [int(d.strftime("%Y%m%d")) for d in days],
        # 2019 年之前稳定为正，2019 年起转负：前推必须暴露这一点
        "net": [0.01 + (i % 7) * 0.001 if d.year < 2019 else -0.01 for i, d in enumerate(days)],
    })
    base = rows.assign(strategy="base", net=0.0)
    result = walkforward(pd.concat([rows, base]), {"cand": 20}, "base", 2020)
    first = result["folds"][0]
    assert first["test_year"] == 2019 and first["selected"] == "cand"
    assert first["test"]["avg_net_return_pct"] < 0
    assert result["passed"] is False


def test_cell_t_stat() -> None:
    cell = _cell(pd.Series([0.01, 0.02, 0.03]))
    assert cell["trades"] == 3 and cell["t_stat"] > 0
