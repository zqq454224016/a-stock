import numpy as np
import pandas as pd
from quant_system.strategy.overnight import SPECS, signal_mask, backtest

def test_overnight_specs_are_separate_and_t1_proxy_is_explicit():
    close = np.linspace(10, 20, 120)
    frame = pd.DataFrame({"open": close, "high": close * 1.02, "low": close * .98, "close": close, "volume": np.full(120, 1000)})
    assert {x.name for x in SPECS} == {"overnight_close_breakout", "overnight_close_pullback", "overnight_strong_turnover"}
    result = backtest(frame, SPECS[0])
    assert result["proxy"] is True

def test_overnight_signal_does_not_use_future_bars():
    close = np.linspace(10, 20, 120)
    frame = pd.DataFrame({"open": close, "high": close * 1.02, "low": close * .98, "close": close, "volume": np.full(120, 1000)})
    before = signal_mask(frame.iloc[:100], SPECS[0]).iloc[-1]
    changed = frame.copy(); changed.loc[100:, "close"] = 999
    after = signal_mask(changed, SPECS[0]).iloc[99]
    assert before == after
