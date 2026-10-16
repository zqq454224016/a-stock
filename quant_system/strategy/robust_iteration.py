"""Cost-aware, purged out-of-sample tournament for trend strategy revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from quant_system.strategy.portfolio_execution import simulate_portfolio

HORIZON = 20
EMBARGO = 60
DIAGNOSTIC_HOLDOUT_DAYS = 60
TRANSACTION_FEE_RATE = 0.00008  # 万0.8，单边
ROUND_TRIP_COST = TRANSACTION_FEE_RATE * 2
MIN_TRAIN_TRADES = 200
MIN_SEGMENT_TRADES = 100


def slippage_rate(amount: float | None) -> float:
    """Conservative one-way slippage tier based on daily traded amount."""
    value = float(amount or 0)
    if value <= 0:
        return .003
    if value < 20_000_000:
        return .003
    if value < 50_000_000:
        return .0015
    if value < 100_000_000:
        return .0008
    return .0003


@dataclass(frozen=True)
class Candidate:
    name: str
    score_floor: float
    volatility_cap: float
    mode: str
    allowed_regimes: tuple[str, ...] = ()
    max_hold_days: int = HORIZON
    stop_loss: float | None = None
    exit_mode: str = "fixed"
    horizon: str = "swing"
    source_id: str = "internal_baseline"


CANDIDATES = (
    Candidate("baseline_long_only", 65, 1000, "baseline"),
    Candidate("baseline_short", 65, 1000, "baseline", max_hold_days=5, horizon="short"),
    Candidate("baseline_medium", 65, 1000, "baseline", max_hold_days=60, horizon="medium"),
    Candidate("baseline_long", 65, 1000, "baseline", max_hold_days=60, horizon="long"),
    Candidate("strict_trend_65", 65, 65, "strict"),
    Candidate("strict_trend_70", 70, 55, "strict"),
    Candidate("pullback_trend", 58, 60, "pullback"),
    Candidate("recovery_confirmed", 58, 65, "recovery"),
    # Adapted from tickflow-stock-panel built-ins. Thresholds are frozen before OOS.
    Candidate("tf_trend_breakout", 0, 1000, "tf_trend_breakout"),
    Candidate("tf_bullish_alignment", 0, 1000, "tf_bullish_alignment"),
    Candidate("tf_macd_golden_volume", 0, 1000, "tf_macd_golden"),
    Candidate("tf_volume_price_surge", 0, 1000, "tf_volume_price"),
    Candidate("tf_low_volatility_leader", 0, 30, "tf_low_volatility"),
    Candidate("tf_pullback_ma20_bounce", 0, 1000, "tf_pullback_ma20"),
    Candidate("tf_low_volatility_regime", 0, 30, "tf_low_volatility", ("rising", "range")),
    Candidate("tf_pullback_rising_regime", 0, 1000, "tf_pullback_ma20", ("rising",)),
    # v15.2: multi-regime control against rising-only overfit; same signal family.
    Candidate("tf_pullback_multi_regime", 0, 1000, "tf_pullback_ma20", ("rising", "range")),
    # Tighter bounce: requires stronger score to cut same-day signal floods.
    Candidate("tf_pullback_rising_strict", 58, 60, "tf_pullback_ma20", ("rising",)),
    # 用户提供的“死蜘蛛”形态：MA5/MA10/MA20 由多头转为空头，
    # 价格跌破共同成本区并伴随量压；仅作为风险/退出实验，不直接产生买入信号。
    Candidate("study_dead_spider_exit", 0, 1000, "dead_spider", ("rising", "range"),
              max_hold_days=5, stop_loss=-.03, exit_mode="ma20_or_ma5_dead", horizon="short",
              source_id="pdf_dead_spider_section_17"),
    Candidate("study_one_yang_triangle托", 0, 1000, "one_yang_triangle托", ("range", "rising"),
              max_hold_days=20, stop_loss=-.05, exit_mode="ma20", horizon="swing",
              source_id="pdf_one_yang_triangle托_section_19"),
    Candidate("tf_low_volatility_regime_exit", 0, 30, "tf_low_volatility", ("rising", "range"), 30, -.05, "ma20"),
    Candidate("tf_pullback_rising_exit", 0, 1000, "tf_pullback_ma20", ("rising",), 15, -.05, "ma20_or_ma5_dead"),
    Candidate(
        "tf_pullback_short_rising", 0, 1000, "tf_pullback_ma20", ("rising",),
        max_hold_days=5, stop_loss=-.03, exit_mode="ma20_or_ma5_dead", horizon="short",
    ),
    Candidate(
        "tf_breakout_short_hot", 0, 1000, "tf_trend_breakout", ("rising",),
        max_hold_days=5, stop_loss=-.03, exit_mode="ma20", horizon="short",
    ),
    Candidate(
        "tf_low_volatility_medium", 0, 30, "tf_low_volatility", ("rising", "range"),
        max_hold_days=60, stop_loss=-.08, exit_mode="ma20", horizon="medium",
    ),
    Candidate(
        "tf_bullish_alignment_medium", 0, 1000, "tf_bullish_alignment", ("rising",),
        max_hold_days=60, stop_loss=-.08, exit_mode="ma20", horizon="medium",
    ),
    Candidate(
        "long_quality_trend_gate", 0, 1000, "long_quality_trend_gate", ("rising", "range"),
        max_hold_days=60, stop_loss=-.10, exit_mode="ma20", horizon="long",
        source_id="long_term_quality_v1",
    ),
    # Moskowitz, Ooi and Pedersen (2012): use the sign of the instrument's
    # trailing 12-month return, skipping the most recent month, and hold for
    # one month. This is a preregistered transfer hypothesis: the paper studies
    # liquid futures/forwards, so A-share applicability must be rejected unless
    # it survives forward shadow validation.
    Candidate(
        "paper_tsmom_12_1_monthly", 0, 1000, "paper_tsmom_12_1",
        max_hold_days=20, exit_mode="fixed", horizon="swing",
        source_id="moskowitz_ooi_pedersen_2012",
    ),
    # Preregistered 2026-08-11 from the three user-supplied price-action and
    # moving-average study notes.  Each lane represents one distinct hypothesis;
    # thresholds are deliberately frozen instead of grid-searched on history.
    Candidate(
        "study_monthly_ma_volume", 0, 1000, "study_monthly_ma_volume",
        max_hold_days=20, stop_loss=-.06, exit_mode="ma20", horizon="swing",
        source_id="monthly_ma_course_section_6",
    ),
    Candidate(
        "study_pa_breakout_followthrough", 0, 1000, "study_pa_breakout_followthrough",
        ("rising",), max_hold_days=5, stop_loss=-.03, exit_mode="ma20", horizon="short",
        source_id="al_brooks_37a",
    ),
    Candidate(
        "study_pa_second_entry_pullback", 0, 1000, "study_pa_second_entry_pullback",
        ("rising",), max_hold_days=20, stop_loss=-.05,
        exit_mode="ma20_or_ma5_dead", horizon="swing", source_id="z_price_action_notes",
    ),
    Candidate(
        "study_pa_range_edge_reversal", 0, 1000, "study_pa_range_edge_reversal",
        ("range",), max_hold_days=5, stop_loss=-.03, exit_mode="fixed", horizon="short",
        source_id="al_brooks_37a_and_z_notes",
    ),
    # v15.3 preregistered 2026-10-16: portfolio-survivable sparse entries.
    # Hypotheses frozen before this OOS re-evaluation; no threshold search on
    # the same contaminated diagnostic window.
    Candidate(
        "v153_pullback_quiet_rising", 0, 30, "tf_pullback_quiet", ("rising",),
        max_hold_days=20, stop_loss=-.05, exit_mode="ma20", horizon="swing",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    Candidate(
        "v153_pullback_volume_rising", 0, 1000, "tf_pullback_volume", ("rising",),
        max_hold_days=20, stop_loss=-.05, exit_mode="ma20", horizon="swing",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    Candidate(
        "v153_lowvol_pullback_multi", 0, 30, "tf_low_vol_pullback", ("rising", "range"),
        max_hold_days=20, stop_loss=-.05, exit_mode="ma20", horizon="swing",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    Candidate(
        "v153_pullback_rising_fast_exit", 0, 1000, "tf_pullback_ma20", ("rising",),
        max_hold_days=10, stop_loss=-.04, exit_mode="ma20_or_ma5_dead", horizon="swing",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    Candidate(
        "v153_tsmom_quiet", 0, 35, "paper_tsmom_quiet",
        max_hold_days=20, exit_mode="fixed", horizon="swing",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    Candidate(
        "v153_pullback_quiet_short", 0, 30, "tf_pullback_quiet", ("rising", "range"),
        max_hold_days=5, stop_loss=-.03, exit_mode="ma20_or_ma5_dead", horizon="short",
        source_id="v15_3_sparse_portfolio_20261016",
    ),
    # v15.5 preregistered: reduce capacity loss by avoiding crowded/extreme
    # momentum entries and shortening the holding window. This is a frozen
    # hypothesis, not a parameter search on the current diagnostic window.
    Candidate(
        "v155_pullback_capacity_guard", 65, 28, "tf_pullback_capacity", ("rising", "range"),
        max_hold_days=8, stop_loss=-.04, exit_mode="ma20_or_ma5_dead", horizon="swing",
        source_id="v15_5_capacity_guard_20261016",
    ),
)


def features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy().reset_index(drop=True)
    for column in ("open", "high", "low", "close", "volume"):
        work[column] = pd.to_numeric(work.get(column), errors="coerce")
    close = work["close"]
    work["ma20"] = close.rolling(20).mean()
    work["ma60"] = close.rolling(60).mean()
    work["ma5"] = close.rolling(5).mean()
    work["ma10"] = close.rolling(10).mean()
    work["high60"] = work["high"].rolling(60).max()
    work["vol_ma5"] = work["volume"].rolling(5).mean()
    work["vol_ratio5"] = work["volume"] / work["vol_ma5"]
    work["vol_ma20"] = work["volume"].rolling(20).mean()
    work["vol_ratio20"] = work["volume"] / work["vol_ma20"]
    work["dead_spider"] = (
        (work["ma5"] < work["ma10"]) & (work["ma10"] < work["ma20"]) &
        (work["close"] < work["ma20"]) & (work["vol_ratio5"] >= 1.2)
    )
    work["one_yang_triangle托"] = (
        (work["close"] > work["open"])
        & (work["close"] > work["ma5"])
        & (work["close"] > work["ma10"])
        & (work["close"] > work["ma20"])
        & (work["open"] < work["ma5"])
        & (work["vol_ratio5"] >= 1.5)
        & (work["close"] >= work["high"].rolling(20).max().shift(1))
    )
    work["change"] = close.pct_change()
    work["mom20"] = close.pct_change(20) * 100
    work["mom60"] = close.pct_change(60) * 100
    work["mom252_skip21"] = (close.shift(21) / close.shift(252) - 1) * 100
    work["slope"] = work["ma20"].pct_change(10) * 100
    work["volatility"] = close.pct_change().rolling(20).std() * np.sqrt(252) * 100
    bar_range = (work["high"] - work["low"]).replace(0, np.nan)
    work["body_ratio"] = (close - work["open"]).abs() / bar_range
    work["close_location"] = (close - work["low"]) / bar_range
    work["prior_high20"] = work["high"].rolling(20).max().shift(1)
    work["prior_low20"] = work["low"].rolling(20).min().shift(1)
    path_length = close.diff().abs().rolling(20).sum()
    work["trend_efficiency20"] = (close - close.shift(20)).abs() / path_length.replace(0, np.nan)
    work["range_position20"] = (
        (close - work["prior_low20"])
        / (work["prior_high20"] - work["prior_low20"]).replace(0, np.nan)
    )
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    work["macd_dif"] = ema12 - ema26
    work["macd_dea"] = work["macd_dif"].ewm(span=9, adjust=False).mean()
    work["score"] = (
        50 + work["mom20"].fillna(0) * 1.2 + work["mom60"].fillna(0) * .35
        + work["slope"].fillna(0) * 2 + np.where(close > work["ma20"], 6, -6)
        + np.where(work["ma20"] > work["ma60"], 8, -8)
    ).clip(0, 100)
    return work


def signal_mask(work: pd.DataFrame, candidate: Candidate) -> pd.Series:
    common = (work["score"] >= candidate.score_floor) & (work["volatility"] <= candidate.volatility_cap)
    if candidate.mode == "tf_trend_breakout":
        return (work["close"] > work["ma60"]) & (work["close"] >= work["high60"]) & (work["vol_ratio5"] >= 2)
    if candidate.mode == "tf_bullish_alignment":
        return (work["ma5"] > work["ma10"]) & (work["ma10"] > work["ma20"]) & (work["ma20"] > work["ma60"]) & (work["mom20"] > 0)
    if candidate.mode == "tf_macd_golden":
        golden = (work["macd_dif"] > work["macd_dea"]) & (work["macd_dif"].shift(1) <= work["macd_dea"].shift(1))
        return golden & (work["vol_ratio5"] >= 1.5)
    if candidate.mode == "tf_volume_price":
        breakout = (work["close"] > work["ma20"]) & (work["close"].shift(1) <= work["ma20"].shift(1))
        return breakout & (work["vol_ratio5"] >= 2) & (work["close"] > work["open"])
    if candidate.mode == "tf_low_volatility":
        return (work["mom20"] > 0) & (work["volatility"] < 30) & (work["close"] > work["ma20"])
    if candidate.mode == "long_quality_trend_gate":
        if not {"fundamental_quality_pass", "fundamental_quality_known"}.issubset(work.columns):
            return pd.Series(False, index=work.index)
        return (work["fundamental_quality_known"].fillna(False).astype(bool)
                & work["fundamental_quality_pass"].fillna(False).astype(bool)
                & (work["close"] > work["ma60"]) & (work["ma20"] > work["ma60"])
                & (work["mom60"] > 0))
    if candidate.mode == "dead_spider":
        # 该形态用于验证下跌/退出风险，禁止作为做多入场信号。
        return work["dead_spider"] & work["dead_spider"].shift(1).fillna(False).eq(False)
    if candidate.mode == "one_yang_triangle托":
        return work["one_yang_triangle托"]
    if candidate.mode == "tf_pullback_ma20":
        proximity = (work["close"] / work["ma20"] - 1).abs()
        return common & (proximity < .02) & (work["ma5"] > work["ma20"]) & (work["ma20"] > work["ma60"]) & (work["change"] > 0)
    if candidate.mode == "tf_pullback_quiet":
        # Sparse rising/range pullback: require realized vol below cap via common.
        proximity = (work["close"] / work["ma20"] - 1).abs()
        return (
            common & (proximity < .02) & (work["ma5"] > work["ma20"])
            & (work["ma20"] > work["ma60"]) & (work["change"] > 0)
            & (work["mom20"] > 0) & (work["vol_ratio20"] <= 1.5)
        )
    if candidate.mode == "tf_pullback_volume":
        proximity = (work["close"] / work["ma20"] - 1).abs()
        return (
            common & (proximity < .02) & (work["ma5"] > work["ma20"])
            & (work["ma20"] > work["ma60"]) & (work["change"] > 0)
            & (work["vol_ratio5"] >= 1.2) & (work["close"] > work["open"])
        )
    if candidate.mode == "tf_low_vol_pullback":
        proximity = (work["close"] / work["ma20"] - 1).abs()
        return (
            common & (work["mom20"] > 0) & (work["volatility"] < 30)
            & (work["close"] > work["ma20"]) & (proximity < .025)
            & (work["ma5"] > work["ma20"]) & (work["change"] > 0)
        )
    if candidate.mode == "tf_pullback_capacity":
        proximity = (work["close"] / work["ma20"] - 1).abs()
        return (
            common & (work["mom20"].between(0, 8))
            & (work["close"] > work["ma20"]) & (proximity < .018)
            & (work["ma5"] > work["ma20"]) & (work["ma20"] > work["ma60"])
            & (work["close_location"] >= .60) & (work["change"] > 0)
            & (work["vol_ratio20"] <= 1.35)
        )
    if candidate.mode == "paper_tsmom_quiet":
        return common & (work["mom252_skip21"] > 0) & (work["volatility"] < 35)
    if candidate.mode == "paper_tsmom_12_1":
        return work["mom252_skip21"] > 0
    if candidate.mode == "study_monthly_ma_volume":
        three_lines_up = (
            (work["ma5"] > work["ma5"].shift(3))
            & (work["ma10"] > work["ma10"].shift(3))
            & (work["ma20"] > work["ma20"].shift(3))
        )
        return (
            three_lines_up & (work["ma5"] > work["ma10"])
            & (work["ma10"] > work["ma20"]) & (work["close"] > work["ma20"])
            & (work["vol_ratio20"] >= 1.10) & (work["close_location"] >= .55)
        )
    if candidate.mode == "study_pa_breakout_followthrough":
        previous_breakout = work["close"].shift(1) > work["prior_high20"].shift(1)
        return (
            previous_breakout & (work["close"] > work["prior_high20"].shift(1))
            & (work["change"] > 0) & (work["body_ratio"] >= .50)
            & (work["close_location"] >= .70) & (work["vol_ratio20"] >= 1.10)
        )
    if candidate.mode == "study_pa_second_entry_pullback":
        touch = work["low"] <= work["ma20"] * 1.02
        earlier_touch = touch.shift(3).rolling(7).max().fillna(0).astype(bool)
        second_test_confirmed = (
            touch.shift(1).fillna(False)
            & (work["close"] > work["high"].shift(1))
            & (work["close"] > work["open"])
        )
        return (
            earlier_touch & second_test_confirmed
            & (work["ma10"] > work["ma20"]) & (work["ma20"] > work["ma20"].shift(5))
            & (work["mom60"] > 0) & (work["close_location"] >= .60)
        )
    if candidate.mode == "study_pa_range_edge_reversal":
        lower_edge_failure = (
            (work["low"] < work["prior_low20"])
            & (work["close"] > work["prior_low20"])
        )
        return (
            lower_edge_failure & (work["trend_efficiency20"] <= .25)
            & (work["range_position20"] <= .35) & (work["close_location"] >= .65)
            & (work["close"] > work["open"])
        )
    if candidate.mode == "baseline":
        return common & (work["ma20"] > work["ma60"])
    if candidate.mode == "strict":
        return common & (work["close"] > work["ma20"]) & (work["ma20"] > work["ma60"]) & (work["slope"] > 0) & (work["mom20"] > 0)
    if candidate.mode == "pullback":
        distance = (work["close"] / work["ma20"] - 1).abs()
        return common & (work["ma20"] > work["ma60"]) & (work["mom60"] > 0) & (distance <= .04) & work["mom20"].between(-3, 12)
    return common & (work["close"] > work["ma20"]) & (work["slope"] > 0) & (work["mom20"] > 0) & (work["mom60"] > -5)


def trades(
    frame: pd.DataFrame,
    candidate: Candidate,
    market_regimes: dict[str, str] | None = None,
    execution_by_date: dict[str, dict[str, Any]] | None = None,
    code: str = "",
    prepared: bool = False,
    allow_incomplete_exit: bool = False,
) -> pd.DataFrame:
    """Create non-overlapping trades: signal at close, enter next open (T+1), exit 20 closes later."""
    work = frame.copy().reset_index(drop=True) if prepared else features(frame)
    mask = signal_mask(work, candidate).fillna(False)
    if candidate.allowed_regimes:
        date_values = work.get("date", work.get("trade_date", pd.Series("", index=work.index)))
        regimes = date_values.astype(str).str[:10].map(market_regimes or {})
        mask &= regimes.isin(candidate.allowed_regimes)
    rows: list[dict[str, float | int]] = []
    next_allowed = 0
    for signal_at in np.flatnonzero(mask.to_numpy()):
        entry_at = signal_at + 1
        exit_at = signal_at + 1 + candidate.max_hold_days
        incomplete_exit = False
        if entry_at >= len(work):
            continue
        if exit_at >= len(work):
            if not allow_incomplete_exit:
                continue
            exit_at = len(work) - 1
            if exit_at <= entry_at:
                continue
            incomplete_exit = True
        if entry_at < next_allowed:
            continue
        entry = work.at[entry_at, "open"]
        date_column = "date" if "date" in work.columns else "trade_date"
        entry_date = str(work.at[entry_at, date_column])[:10] if date_column in work.columns else str(entry_at)
        entry_execution = (execution_by_date or {}).get(entry_date) or {}
        if entry_execution.get("suspended") or entry_execution.get("one_price_limit_up"):
            continue
        if not np.isfinite(entry) or entry <= 0:
            entry = work.at[entry_at, "close"]
        exit_price = work.at[exit_at, "close"]
        exit_reason = "data_end" if incomplete_exit else "max_hold"
        scan_days = range(entry_at + 1, exit_at + 1) if (
            candidate.stop_loss is not None or candidate.exit_mode != "fixed"
        ) else ()
        for day in scan_days:
            day_date = str(work.at[day, date_column])[:10] if date_column in work.columns else str(day)
            day_execution = (execution_by_date or {}).get(day_date) or {}
            if day_execution.get("suspended") or day_execution.get("one_price_limit_down"):
                continue
            if candidate.stop_loss is not None:
                stop_price = entry * (1 + candidate.stop_loss)
                day_low = work.at[day, "low"]
                if np.isfinite(day_low) and day_low <= stop_price:
                    day_open = work.at[day, "open"]
                    exit_price = min(stop_price, day_open) if np.isfinite(day_open) else stop_price
                    exit_at, exit_reason = day, "stop_loss"
                    break
            previous = day - 1
            ma20_exit = work.at[previous, "close"] < work.at[previous, "ma20"]
            ma5_dead = (
                work.at[previous, "ma5"] < work.at[previous, "ma20"]
                and previous > 0
                and work.at[previous - 1, "ma5"] >= work.at[previous - 1, "ma20"]
            )
            should_exit = candidate.exit_mode == "ma20" and ma20_exit
            should_exit |= candidate.exit_mode == "ma20_or_ma5_dead" and (ma20_exit or ma5_dead)
            if should_exit:
                day_open = work.at[day, "open"]
                exit_price = day_open if np.isfinite(day_open) else work.at[day, "close"]
                exit_at, exit_reason = day, "signal_exit"
                break
        exit_date_candidate = str(work.at[exit_at, date_column])[:10] if date_column in work.columns else str(exit_at)
        exit_execution = (execution_by_date or {}).get(exit_date_candidate) or {}
        if exit_execution.get("suspended") or exit_execution.get("one_price_limit_down"):
            deferred = None
            for day in range(exit_at + 1, len(work)):
                day_date = str(work.at[day, date_column])[:10] if date_column in work.columns else str(day)
                constraint = (execution_by_date or {}).get(day_date) or {}
                if not constraint.get("suspended") and not constraint.get("one_price_limit_down"):
                    deferred = day
                    break
            if deferred is None:
                if not allow_incomplete_exit:
                    continue
                # Keep last available bar as forced shadow exit.
            else:
                exit_at, exit_reason = deferred, "deferred_untradable"
                day_open = work.at[exit_at, "open"]
                exit_price = day_open if np.isfinite(day_open) else work.at[exit_at, "close"]
        lows = work.loc[entry_at:exit_at, "low"].dropna()
        if not np.isfinite(entry) or not np.isfinite(exit_price) or entry <= 0:
            continue
        gross = exit_price / entry - 1
        entry_amount = work.at[entry_at, "amount"] if "amount" in work.columns else 0
        slip = slippage_rate(entry_amount)
        total_cost = ROUND_TRIP_COST + slip * 2
        mae = (lows.min() / entry - 1) if not lows.empty else min(gross, 0)
        exit_date = str(work.at[exit_at, date_column])[:10] if date_column in work.columns else str(exit_at)
        daily_marks = []
        for day in range(entry_at, exit_at + 1):
            mark_date = str(work.at[day, date_column])[:10] if date_column in work.columns else str(day)
            mark_close = work.at[day, "close"]
            if np.isfinite(mark_close) and mark_close > 0:
                mark_return = float(mark_close / entry - 1 - TRANSACTION_FEE_RATE - slip)
                if day == exit_at:
                    mark_return = float(gross - total_cost)
                daily_marks.append({"date": mark_date, "return": mark_return})
        rows.append({
            "code": code,
            "signal_at": int(signal_at), "entry_at": entry_at, "exit_at": exit_at,
            "entry_date": entry_date, "exit_date": exit_date, "exit_reason": exit_reason,
            # Reuse the pre-existing deterministic score for same-day
            # cross-sectional ordering.  This does not introduce a new model or
            # allow the portfolio simulator to tune weights from OOS results.
            "signal_score": float(work.at[signal_at, "score"]),
            "net_return": gross - total_cost, "mae": mae, "daily_marks": daily_marks,
            "slippage_one_way": slip, "transaction_cost": total_cost,
        })
        next_allowed = exit_at + 1
    return pd.DataFrame(rows)


def summarize(parts: list[pd.DataFrame]) -> dict[str, Any]:
    data = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if data.empty:
        return {"trades": 0, "hit_rate": None, "avg_net_return_pct": None, "median_net_return_pct": None, "max_drawdown_pct": None, "avg_mae_pct": None}
    returns = data["net_return"].astype(float)
    portfolio = simulate_portfolio(data)
    return {
        "trades": int(len(data)),
        "hit_rate": round(float((returns > 0).mean()), 4),
        "avg_net_return_pct": round(float(returns.mean() * 100), 4),
        "median_net_return_pct": round(float(returns.median() * 100), 4),
        "max_drawdown_pct": portfolio["max_drawdown_pct"],
        "avg_mae_pct": round(float(data["mae"].mean() * 100), 4),
        "portfolio": portfolio,
    }


def diagnostic_holdout_boundary(bars: int, holdout_days: int = DIAGNOSTIC_HOLDOUT_DAYS) -> int:
    """Return the first bar of the strictly isolated recent diagnostic window."""
    if bars < 0:
        raise ValueError("bars must be non-negative")
    if holdout_days <= 0:
        raise ValueError("holdout_days must be positive")
    return max(0, bars - holdout_days)


def split_research_and_diagnostic_holdout(
    data: pd.DataFrame,
    bars: int,
    holdout_days: int = DIAGNOSTIC_HOLDOUT_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate selectable research trades from the non-selectable recent window.

    A research trade must be fully closed before T-60.  A diagnostic trade must
    have its signal in the latest 60 trading bars.  Trades crossing the boundary
    are deliberately excluded from both sets, preventing future holdout prices
    from leaking into candidate development or selection.
    """
    if data.empty:
        return data.copy(), data.copy()
    boundary = diagnostic_holdout_boundary(bars, holdout_days)
    research = data[data["exit_at"] < boundary].copy()
    diagnostic_holdout = data[data["signal_at"] >= boundary].copy()
    return research, diagnostic_holdout


def split_trades(data: pd.DataFrame, bars: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compatibility wrapper returning research and diagnostic-only holdout."""
    return split_research_and_diagnostic_holdout(data, bars)


def development_segments(data: pd.DataFrame, bars: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two purged selectable segments, both ending strictly before T-60."""
    research_end = diagnostic_holdout_boundary(bars)
    boundary = research_end // 2
    first = data[data["exit_at"] < max(0, boundary - EMBARGO)].copy() if not data.empty else data
    second = data[
        (data["signal_at"] >= boundary)
        & (data["exit_at"] < research_end)
    ].copy() if not data.empty else data
    return first, second


def _portfolio_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    portfolio = payload.get("portfolio")
    return portfolio if isinstance(portfolio, dict) else {}


def portfolio_promotion_passed(champion: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """Require the cash-constrained portfolio path itself to be tradeable.

    Adversarial v15.4: capacity-starved floods (拒单 >> 接受) cannot promote even if
    a thin accepted subset looks lucky — that edge is not recommendation-ready.
    """
    champion_port = _portfolio_metrics(champion)
    baseline_port = _portfolio_metrics(baseline)
    accepted = int(champion_port.get("accepted_trades") or 0)
    rejected = int(champion_port.get("rejected_capacity") or 0)
    if accepted < 30:
        return False
    # 拒单五倍于接受 → 边在容量下消失，与正式推荐「可执行」不对齐。
    if rejected > accepted * 5:
        return False
    champion_ret = float(champion_port.get("total_return_pct") or -99)
    baseline_ret = float(baseline_port.get("total_return_pct") or -99)
    champion_hit = champion_port.get("hit_rate")
    if champion_hit is None:
        return False
    return bool(
        champion_ret > 0
        and champion_ret > baseline_ret
        and float(champion_hit) >= 0.50
        and float(champion_port.get("max_drawdown_pct") or -100)
        >= float(baseline_port.get("max_drawdown_pct") or -100)
    )


def promotion_passed(
    champion: dict[str, Any],
    baseline: dict[str, Any],
    stability: list[dict[str, Any]] | None = None,
) -> bool:
    stable = stability or []
    signal_ok = bool(
        len(stable) >= 2
        and all(
            segment.get("trades", 0) >= MIN_SEGMENT_TRADES
            and segment.get("avg_net_return_pct", -99) > 0
            and segment.get("median_net_return_pct", -99) > 0
            for segment in stable
        )
        and
        champion.get("trades", 0) >= 300
        and champion.get("hit_rate", 0) >= max(.54, baseline.get("hit_rate") or 0)
        and champion.get("avg_net_return_pct", -99) > max(0, baseline.get("avg_net_return_pct") or -99)
        and champion.get("median_net_return_pct", -99) > 0
        and champion.get("max_drawdown_pct", -100) >= (baseline.get("max_drawdown_pct") or -100)
    )
    # v15.2: signal edge that dies under capacity/correlation is not promotable.
    return signal_ok and portfolio_promotion_passed(champion, baseline)
