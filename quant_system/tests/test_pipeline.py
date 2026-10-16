"""pipeline 单元测试。"""

import pandas as pd

from quant_system.pipeline.adjuster import apply_adjustment, calc_ma
from quant_system.pipeline.cleaner import clean_kline_df, clean_spot_df
from quant_system.apps import pipeline


def _sample_kline():
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=30),
        "open": [10.0] * 30,
        "high": [11.0] * 30,
        "low": [9.0] * 30,
        "close": [10.5] * 30,
        "volume": [1000.0] * 30,
    })


def test_clean_kline():
    df = _sample_kline()
    cleaned = clean_kline_df(df)
    assert len(cleaned) == 30


def test_apply_adjustment():
    df = apply_adjustment(_sample_kline(), adj_type="qfq")
    assert "adj_type" in df.columns
    assert df["adj_type"].iloc[0] == "qfq"


def test_calc_ma():
    df = calc_ma(_sample_kline())
    assert "ma5" in df.columns
    assert "ma20" in df.columns


def test_clean_spot():
    df = pd.DataFrame({
        "代码": ["sh600519"],
        "名称": ["贵州茅台"],
        "最新价": [1200.0],
        "涨跌幅": [1.5],
        "成交额": [1e9],
    })
    cleaned = clean_spot_df(df)
    assert len(cleaned) == 1


def test_all_pipeline_runs_iteration_audit(monkeypatch):
    calls = []
    for name in (
        "run_phase1_market_data", "run_interim_financial_job", "run_daily_market",
        "run_public_supplement_job",
        "run_daily_stock", "run_factor_compute", "run_today_change_job",
        "run_trend_strategy_job", "run_recommendation_job", "run_auto_iteration",
        "run_monitoring_job", "launch_sector_data_job",
    ):
        monkeypatch.setattr(pipeline, name, lambda *args, _name=name, **kwargs: calls.append(_name))
    monkeypatch.setattr(pipeline, "launch_offline_validation", lambda: calls.append("launch_offline_validation"))
    monkeypatch.setattr(pipeline, "launch_iteration_worker", lambda: calls.append("launch_iteration_worker"))

    pipeline.run_all_pipeline(skip_inspect=True)

    assert calls.index("run_recommendation_job") < calls.index("run_auto_iteration")
    assert calls.index("run_auto_iteration") < calls.index("run_monitoring_job")
    assert calls[-1] == "launch_iteration_worker"
