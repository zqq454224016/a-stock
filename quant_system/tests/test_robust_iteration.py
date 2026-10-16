import numpy as np
import pandas as pd

from quant_system.strategy.robust_iteration import (
    CANDIDATES,
    development_segments,
    diagnostic_holdout_boundary,
    slippage_rate,
    split_research_and_diagnostic_holdout,
    split_trades,
    features,
    signal_mask,
    trades,
)


def test_trades_are_t1_cost_aware_and_non_overlapping():
    count = 260
    close = np.linspace(10, 20, count)
    frame = pd.DataFrame({
        "open": close,
        "high": close * 1.01,
        "low": close * .99,
        "close": close,
        "volume": np.full(count, 1_000_000),
    })
    result = trades(frame, CANDIDATES[1])
    assert not result.empty
    assert (result["entry_at"] == result["signal_at"] + 1).all()
    assert (result["signal_at"].iloc[1:].to_numpy() >= result["exit_at"].iloc[:-1].to_numpy()).all()
    assert result["signal_score"].between(0, 100).all()
    assert (result["net_return"] > 0).all()


def test_split_strictly_isolates_latest_60_bars_as_diagnostic_only():
    count = 500
    close = np.linspace(10, 30, count)
    frame = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1})
    research, diagnostic_holdout = split_trades(trades(frame, CANDIDATES[0]), count)
    assert diagnostic_holdout_boundary(count) == 440
    assert research.empty or research["exit_at"].max() < 440
    assert diagnostic_holdout.empty or diagnostic_holdout["signal_at"].min() >= 440


def test_boundary_crossing_trades_are_excluded_from_both_sets():
    data = pd.DataFrame({
        "signal_at": [400, 430, 440, 470],
        "exit_at": [420, 450, 460, 490],
        "net_return": [.01, .02, -.03, .04],
    })
    research, diagnostic_holdout = split_research_and_diagnostic_holdout(data, bars=500)
    assert research["signal_at"].tolist() == [400]
    assert diagnostic_holdout["signal_at"].tolist() == [440, 470]


def test_development_segments_never_read_diagnostic_holdout():
    data = pd.DataFrame({
        "signal_at": np.arange(500),
        "exit_at": np.arange(500),
        "net_return": np.zeros(500),
    })
    early, late = development_segments(data, bars=500)
    assert early["exit_at"].max() < 160
    assert late["signal_at"].min() >= 220
    assert late["exit_at"].max() < 440


def test_holdout_returns_cannot_change_selectable_research_data():
    data = pd.DataFrame({
        "signal_at": np.arange(500),
        "exit_at": np.arange(500),
        "net_return": np.linspace(-.1, .1, 500),
    })
    research_before, _ = split_research_and_diagnostic_holdout(data, bars=500)
    changed = data.copy()
    changed.loc[changed["signal_at"] >= 440, "net_return"] = 999
    research_after, diagnostic_after = split_research_and_diagnostic_holdout(changed, bars=500)
    pd.testing.assert_frame_equal(research_before, research_after)
    assert (diagnostic_after["net_return"] == 999).all()


def test_slippage_is_higher_for_illiquid_stocks():
    assert slippage_rate(10_000_000) == .003
    assert slippage_rate(60_000_000) == .0008
    assert slippage_rate(500_000_000) == .0003


def test_candidates_cover_separate_horizons_with_baselines():
    names = {(candidate.horizon, candidate.name) for candidate in CANDIDATES}
    assert ("short", "baseline_short") in names
    assert ("swing", "baseline_long_only") in names
    assert ("medium", "baseline_medium") in names
    assert ("long", "baseline_long") in names
    assert ("long", "long_quality_trend_gate") in names


def test_public_tsmom_candidate_uses_preregistered_12_1_rule():
    candidate = next(item for item in CANDIDATES if item.name == "paper_tsmom_12_1_monthly")
    assert candidate.max_hold_days == 20
    assert candidate.mode == "paper_tsmom_12_1"
    assert candidate.source_id == "moskowitz_ooi_pedersen_2012"


def test_study_candidates_are_preregistered_without_parameter_grid():
    study = [item for item in CANDIDATES if item.name.startswith("study_")]
    names = {item.name for item in study}
    assert {
        "study_monthly_ma_volume",
        "study_pa_breakout_followthrough",
        "study_pa_second_entry_pullback",
        "study_pa_range_edge_reversal",
        "study_dead_spider_exit",
        "study_one_yang_triangle托",
    } <= names
    assert len({item.mode for item in study}) >= 4


def test_v15_2_adds_multi_regime_pullback_and_portfolio_gate():
    from quant_system.strategy.robust_iteration import portfolio_promotion_passed

    names = {item.name for item in CANDIDATES}
    assert "tf_pullback_multi_regime" in names
    assert "tf_pullback_rising_strict" in names
    multi = next(item for item in CANDIDATES if item.name == "tf_pullback_multi_regime")
    assert set(multi.allowed_regimes) == {"rising", "range"}
    champion = {
        "trades": 400, "hit_rate": 0.56, "avg_net_return_pct": 1.0,
        "median_net_return_pct": 0.5, "max_drawdown_pct": -5,
        "portfolio": {
            "accepted_trades": 40, "total_return_pct": -10,
            "hit_rate": 0.4, "max_drawdown_pct": -20,
        },
    }
    baseline = {
        "trades": 400, "hit_rate": 0.45, "avg_net_return_pct": -0.1,
        "median_net_return_pct": -0.2, "max_drawdown_pct": -50,
        "portfolio": {
            "accepted_trades": 40, "total_return_pct": -20,
            "hit_rate": 0.4, "max_drawdown_pct": -50,
        },
    }
    assert portfolio_promotion_passed(champion, baseline) is False


def test_v15_4_rejects_capacity_starved_portfolio_even_if_thin_subset_wins():
    from quant_system.strategy.robust_iteration import portfolio_promotion_passed

    champion = {
        "trades": 400, "hit_rate": 0.56, "avg_net_return_pct": 1.0,
        "median_net_return_pct": 0.5, "max_drawdown_pct": -5,
        "portfolio": {
            "accepted_trades": 40, "rejected_capacity": 300,
            "total_return_pct": 8, "hit_rate": 0.55, "max_drawdown_pct": -8,
        },
    }
    baseline = {
        "trades": 400, "hit_rate": 0.45, "avg_net_return_pct": -0.1,
        "median_net_return_pct": -0.2, "max_drawdown_pct": -50,
        "portfolio": {
            "accepted_trades": 40, "total_return_pct": 1,
            "hit_rate": 0.4, "max_drawdown_pct": -50,
        },
    }
    assert portfolio_promotion_passed(champion, baseline) is False
    champion["portfolio"]["rejected_capacity"] = 10
    assert portfolio_promotion_passed(champion, baseline) is True


def test_v15_3_preregisters_sparse_portfolio_hypotheses():
    names = {item.name for item in CANDIDATES}
    expected = {
        "v153_pullback_quiet_rising",
        "v153_pullback_volume_rising",
        "v153_lowvol_pullback_multi",
        "v153_pullback_rising_fast_exit",
        "v153_tsmom_quiet",
        "v153_pullback_quiet_short",
    }
    assert expected <= names
    quiet = next(item for item in CANDIDATES if item.name == "v153_pullback_quiet_rising")
    assert quiet.mode == "tf_pullback_quiet"
    assert quiet.volatility_cap == 30
    assert quiet.source_id == "v15_3_sparse_portfolio_20261016"


def test_long_quality_gate_fails_closed_without_point_in_time_financial_join():
    candidate = next(item for item in CANDIDATES if item.name == "long_quality_trend_gate")
    frame = pd.DataFrame({"open": [10] * 100, "high": [11] * 100, "low": [9] * 100, "close": [10] * 100, "volume": [1000] * 100})
    assert not signal_mask(features(frame), candidate).any()


def test_long_quality_gate_requires_verified_financial_pass():
    candidate = next(item for item in CANDIDATES if item.name == "long_quality_trend_gate")
    close = np.linspace(10, 20, 100)
    frame = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * .99, "close": close, "volume": [1000] * 100,
                          "fundamental_quality_known": [True] * 100, "fundamental_quality_pass": [True] * 100})
    assert bool(signal_mask(features(frame), candidate).iloc[-1])


def test_monthly_ma_signal_requires_all_three_lines_rising_and_volume():
    close = np.concatenate([np.full(30, 10.0), np.linspace(10.1, 14.0, 30)])
    frame = pd.DataFrame({
        "open": close * .995, "high": close * 1.005, "low": close * .99,
        "close": close, "volume": np.concatenate([np.full(59, 1_000_000), [2_000_000]]),
    })
    work = features(frame)
    candidate = next(item for item in CANDIDATES if item.name == "study_monthly_ma_volume")
    assert bool(signal_mask(work, candidate).iloc[-1])


def test_price_action_features_do_not_use_future_bars():
    count = 80
    close = np.linspace(10, 12, count)
    frame = pd.DataFrame({
        "open": close * .995, "high": close * 1.01, "low": close * .99,
        "close": close, "volume": np.full(count, 1_000_000),
    })
    before = features(frame.iloc[:60]).iloc[-1]
    changed = frame.copy()
    changed.loc[60:, ["open", "high", "low", "close"]] = 999
    after = features(changed).iloc[59]
    for column in ("prior_high20", "prior_low20", "trend_efficiency20", "range_position20"):
        assert before[column] == after[column]
