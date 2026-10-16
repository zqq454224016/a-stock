from __future__ import annotations

import pandas as pd

from quant_system.strategy.aggressive_board import SPECS, backtest, signal_mask


def _frame() -> pd.DataFrame:
    rows = []
    price = 10.0
    for index in range(80):
        price *= 1.01
        volume = 100 + index
        # Create a hot breakout-like day near the end.
        if index == 75:
            open_price = price
            close = price * 1.06
            high = close * 1.01
            volume = 500
        else:
            open_price = price * 0.99
            close = price
            high = price * 1.01
        rows.append({
            "open": open_price,
            "high": high,
            "low": open_price * 0.98,
            "close": close,
            "volume": float(volume),
        })
        # stair-step volume into the hot day
        if index in (73, 74):
            rows[-1]["volume"] = 200.0 + (index - 72) * 80
    return pd.DataFrame(rows)


def test_aggressive_specs_are_three_parallel_streams() -> None:
    assert len(SPECS) == 3
    assert {spec.mode for spec in SPECS} == {"breakout", "volume_thrust", "rs_continuation"}


def test_aggressive_backtest_returns_proxy_metrics() -> None:
    frame = _frame()
    result = backtest(frame, SPECS[0])
    assert result["strategy"] == "aggressive_breakout_hot"
    assert result["proxy"] is True
    assert "trades" in result
    # mask should be computable without raising
    mask = signal_mask(frame, SPECS[2])
    assert len(mask) == len(frame)
