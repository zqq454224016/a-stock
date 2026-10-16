from __future__ import annotations

import pandas as pd

from quant_system.strategy.reversal_hunter import ReversalHunterStrategy


def _frame() -> pd.DataFrame:
    rows = []
    for i in range(30):
        close = 10.0 + i * 0.10
        rows.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": close - 0.03,
            "high": close + 0.08,
            "low": close - 0.08,
            "close": close,
            "volume": 1_000_000,
        })
    # Controlled bearish pullback followed by a >=2% bullish body that closes
    # above the previous open (the model's objective body-reversal definition).
    rows[-2].update(open=13.05, high=13.10, low=12.72, close=12.80)
    rows[-1].update(open=12.78, high=13.18, low=12.75, close=13.12, volume=1_100_000)
    return pd.DataFrame(rows)


def test_generates_signal_for_strict_bullish_reversal() -> None:
    result = ReversalHunterStrategy().generate_signals(_frame())
    assert result.iloc[-1]["signal"] == 1
    assert bool(result.iloc[-1]["reversal_setup"]) is True


def test_rejects_reversal_far_below_recent_high() -> None:
    frame = _frame()
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [10.0, 10.4, 9.9, 10.3]
    result = ReversalHunterStrategy().generate_signals(frame)
    assert result.iloc[-1]["signal"] != 1
