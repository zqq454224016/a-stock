"""Run a fixed candidate tournament and preserve every iteration artifact."""

from __future__ import annotations

import hashlib
import gzip
import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.strategy.robust_iteration import (
    CANDIDATES,
    DIAGNOSTIC_HOLDOUT_DAYS,
    MIN_TRAIN_TRADES,
    development_segments,
    features,
    promotion_passed,
    split_trades,
    summarize,
    trades,
)
from quant_system.tasks.strategy_job import _read_stock, _write
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

# v15.3：预登记稀疏组合可存活假设（低波/量能确认/快速退出），禁止同OOS调参。
RESEARCH_VERSION = "15.5.0"
FORWARD_SHADOW_MIN_TRADING_DAYS = 60
FORWARD_SHADOW_MODE = "historical_real_window"


def _forward_shadow_start(as_of: str | None = None) -> str:
    """最近 N 个交易日窗口的起点（含 as_of）。"""
    from quant_system.utils.trade_calendar import get_calendar

    calendar = get_calendar()
    end = as_of or calendar.latest_completed_trade_day()
    days = [day for day in calendar.fetch_dates() if day <= end]
    if len(days) >= FORWARD_SHADOW_MIN_TRADING_DAYS:
        return days[-FORWARD_SHADOW_MIN_TRADING_DAYS]
    return days[0] if days else str(end)


# 兼容旧引用与单测 monkeypatch；正式窗口起点由日历回看计算。
FORWARD_SHADOW_START = ""


def _fingerprint(paths: list[Path], dependencies: list[Path] | None = None) -> str:
    all_paths = paths + [path for path in (dependencies or []) if path.exists()]
    source = RESEARCH_VERSION + "|" + "|".join(
        f"{p.parent.name}/{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in all_paths
    )
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def run_strategy_iteration(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    stock_paths = [
        p for p in sorted((cfg.data_dir / "stocks").glob("*.json"))
        if p.stem != "index" and is_research_stock_code(p.stem)
    ]
    fingerprint_dependencies = [
        # 市场快照更新也必须触发重算；否则仅补齐大盘日期时会被误判为 unchanged_data。
        cfg.data_dir / "latest.json",
        cfg.data_dir / "today_change/summary.json",
        cfg.data_dir / "sector_data/rotation.json",
        cfg.data_dir / "market_regime/five_year.json",
        cfg.data_dir / "execution_history/status.json",
        cfg.data_dir / "market_events/status.json",
    ]
    # 研究逻辑版本也纳入指纹；新增/修改候选（如死蜘蛛）必须触发重算。
    fingerprint = _fingerprint(stock_paths, fingerprint_dependencies) + ":research_v15_3_sparse_portfolio"
    root = cfg.data_dir / "strategy_iterations"
    latest_path = root / "latest.json"
    try:
        previous = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if previous.get("data_fingerprint") == fingerprint and previous.get("status") == "complete":
        return {**previous, "status": "unchanged_data"}

    run_id = now_str().replace("-", "").replace(":", "").replace(" ", "T")
    run_root = root / run_id
    regime_payload = {}
    try:
        regime_payload = json.loads((cfg.data_dir / "market_regime/five_year.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    market_regimes = {
        str(row.get("date"))[:10]: str(row.get("regime"))
        for row in regime_payload.get("items") or []
        if row.get("date") and row.get("regime")
    }
    _write(root / "status.json", {"status": "running", "run_id": run_id, "total": len(stock_paths), "completed": 0})
    buckets: dict[str, dict[str, list[Any]]] = {
        c.name: {"train": [], "development_early": [], "development_late": [], "test": []}
        for c in CANDIDATES
    }
    used = 0
    for index, path in enumerate(stock_paths, 1):
        try:
            stock, frame = _read_stock(path)
            if "ST" in str(stock.get("name") or "").upper() or len(frame) < 500:
                continue
            used += 1
            history_frame = frame.tail(cfg.research_hist_days)
            prepared_frame = features(history_frame)
            execution_by_date: dict[str, dict[str, Any]] = {}
            execution_path = cfg.data_dir / "execution_history" / f"{path.stem}.json.gz"
            if execution_path.exists():
                with gzip.open(execution_path, "rt", encoding="utf-8") as stream:
                    execution_by_date = {
                        str(row.get("date"))[:10]: row for row in json.load(stream)
                        if isinstance(row, dict) and row.get("date")
                    }
            for candidate in CANDIDATES:
                candidate_trades = trades(
                    prepared_frame, candidate, market_regimes, execution_by_date,
                    code=path.stem, prepared=True,
                )
                bars = len(prepared_frame)
                train, test = split_trades(candidate_trades, bars)
                early, late = development_segments(candidate_trades, bars)
                buckets[candidate.name]["train"].append(train)
                buckets[candidate.name]["development_early"].append(early)
                buckets[candidate.name]["development_late"].append(late)
                buckets[candidate.name]["test"].append(test)
        except Exception:
            continue
        if index % 100 == 0:
            _write(root / "status.json", {"status": "running", "run_id": run_id, "total": len(stock_paths), "completed": index, "usable_stocks": used})

    candidates: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        train_metrics = summarize(buckets[candidate.name]["train"])
        test_metrics = summarize(buckets[candidate.name]["test"])
        stability = [
            summarize(buckets[candidate.name]["development_early"]),
            summarize(buckets[candidate.name]["development_late"]),
        ]
        train_score = (train_metrics.get("avg_net_return_pct") or -99) * (train_metrics.get("hit_rate") or 0)
        candidates.append({
            "name": candidate.name, "horizon": candidate.horizon,
            "parameters": candidate.__dict__, "train": train_metrics,
            "development_stability": stability, "oos": test_metrics,
            "train_score": round(train_score, 6),
        })
    eligible = [
        item for item in candidates
        if item["train"]["trades"] >= MIN_TRAIN_TRADES
        and (item["train"]["avg_net_return_pct"] or -99) > 0
        and float(((item["train"].get("portfolio") or {}).get("total_return_pct")) or -99) > 0
        and all((segment.get("avg_net_return_pct") or -99) > 0 for segment in item["development_stability"])
        and all(
            float(((segment.get("portfolio") or {}).get("total_return_pct")) or -99) > 0
            for segment in item["development_stability"]
        )
    ]
    baseline_names = {
        "short": "baseline_short",
        "swing": "baseline_long_only",
        "medium": "baseline_medium",
        "long": "baseline_long",
    }
    horizon_results: dict[str, dict[str, Any]] = {}
    for horizon, baseline_name in baseline_names.items():
        members = [item for item in candidates if item["horizon"] == horizon]
        horizon_eligible = [item for item in eligible if item["horizon"] == horizon]
        selected_horizon = max(horizon_eligible, key=lambda x: x["train_score"]) if horizon_eligible else next(
            item for item in members if item["name"] == baseline_name
        )
        baseline_horizon = next(item for item in members if item["name"] == baseline_name)
        horizon_passed = promotion_passed(
            selected_horizon["oos"], baseline_horizon["oos"], selected_horizon["development_stability"],
        )
        horizon_results[horizon] = {
            "selected_candidate": selected_horizon["name"],
            "baseline_candidate": baseline_name,
            "promotion_passed": horizon_passed,
            "evaluation_scope": "contaminated_recent_60d_diagnostic_only",
            "selected_oos": selected_horizon["oos"],
            "baseline_oos": baseline_horizon["oos"],
        }
    diagnostic_passed_horizons = [name for name, item in horizon_results.items() if item["promotion_passed"]]
    selected = max(eligible, key=lambda x: x["train_score"]) if eligible else candidates[0]
    baseline = next(
        item for item in candidates
        if item["name"] == baseline_names[selected["horizon"]]
    )
    # Every historical OOS interval currently stored by the project has already
    # been inspected during versions 3-11. New public-source hypotheses may be
    # diagnosed on it, but cannot be promoted from it. Only observations
    # collected after this preregistration date can unlock promotion.
    historical_promotion_blocked = True
    passed = bool(diagnostic_passed_horizons) and not historical_promotion_blocked
    payload = {
        "status": "complete", "run_id": run_id, "updated_at": now_str(), "data_fingerprint": fingerprint,
        "research_version": RESEARCH_VERSION,
        "universe_scope": "ordinary_a_share_main_boards_v1",
        "history_bars": cfg.research_hist_days, "universe": len(stock_paths), "usable_stocks": used,
        "market_regime_days": len(market_regimes),
        "execution_constraints": "raw_vs_qfq_with_sh_sz_historical_st_v3",
        "method": {
            "research_cutoff": f"T-{DIAGNOSTIC_HOLDOUT_DAYS}",
            "development_segments": 2,
            "embargo_bars": 60,
            "recent_history_scope": "diagnostic_only_not_selectable",
            "entry": "next_open_T+1",
            "exit": "candidate_specific_next_open_or_stop_or_max_hold",
            # 模拟账户税费：按用户配置“万0.8”折算为 0.8/10000。
            # 旧值 .008 等于单边 0.8%，会把正常策略收益系统性压成负数。
            "transaction_fee_one_way_pct": .00008,
            "round_trip_cost_pct": .00016,
            "initial_cash": 50000,
            "signals": "non_overlapping",
            "feature_calculation": "once_per_stock_shared_by_fixed_candidates",
            "portfolio": "cash_constrained_max10_single10pct_gross95pct_daily_cap2_marking_ranked_entry",
            "same_day_entry_selection": "signal_score_desc_daily_cap2_then_code",
            "selection": "fixed_candidates_using_only_data_at_or_before_T_minus_60",
            "promotion_requires_portfolio_path": True,
        },
        "root_cause": [
            "旧策略把同一持有期内每日信号重复计样，样本不独立",
            "旧推荐使用同一五年结果筛选并展示，存在样本内挑选偏差",
            "旧策略包含做空方向，但普通A股系统并未实现可交易的融券约束",
            "旧回测未扣费用，且 max_adverse 实际是期末最差收益而非持有期不利波动",
            "10.0.0组合在同日容量竞争时按股票代码接受，未按既有确定性信号分数排序",
            "15.1信号级可过线但训练组合亏损：同日相关信号占满仓位，边在容量下消失",
            "15.2低波冠军训练组合强、OOS组合仍负：需稀疏入场与更快释放仓位的预登记假设",
        ],
        "v15_3_preregistration": {
            "date": "2026-10-16",
            "rule": "thresholds_frozen_before_rerun_no_same_oos_tuning",
            "hypotheses": [
                {
                    "id": "v153_pullback_quiet_rising",
                    "claim": "低波回踩在上升市减少同日相关洪水，组合路径更稳",
                    "eliminate_if": "组合OOS收益<=0或命中率<0.50或接受笔数<30",
                },
                {
                    "id": "v153_pullback_volume_rising",
                    "claim": "回踩加量能确认降低假弹，提高组合接受单质量",
                    "eliminate_if": "信号或组合OOS均收益<=0",
                },
                {
                    "id": "v153_lowvol_pullback_multi",
                    "claim": "低波领涨失败因缺少回踩纪律；回踩+多状态可修复OOS组合",
                    "eliminate_if": "range+rising下组合OOS仍<=0",
                },
                {
                    "id": "v153_pullback_rising_fast_exit",
                    "claim": "更快退出释放容量，降低组合路径回撤",
                    "eliminate_if": "组合OOS回撤差于同族慢退出且收益不更高",
                },
                {
                    "id": "v153_tsmom_quiet",
                    "claim": "TSMOM信号边被高波噪声吞没；限波后组合可存活",
                    "eliminate_if": "组合OOS<=0或打不过baseline组合",
                },
                {
                    "id": "v153_pullback_quiet_short",
                    "claim": "短持有低波回踩提高换手，适配日限流组合",
                    "eliminate_if": "短线组合OOS命中率<0.50",
                },
            ],
        },
        "selected_candidate": selected["name"], "selected_horizon": selected["horizon"],
        "promotion_passed": passed,
        "passed_horizons": [] if historical_promotion_blocked else diagnostic_passed_horizons,
        "diagnostic_passed_horizons": diagnostic_passed_horizons,
        "horizon_results": horizon_results,
        "decision": "promote_to_shadow" if passed else "research_diagnostic_wait_forward_shadow",
        "baseline_oos": baseline["oos"], "selected_oos": selected["oos"], "candidates": candidates,
        "anti_overfit": {
            "candidate_space_frozen": True,
            "development_period_consistency_required": True,
            "purge_and_embargo": True,
            "oos_used_for_selection": False,
            "positive_median_required": True,
            "failed_candidate_is_not_retuned_on_same_oos": True,
            "multiple_candidate_hit_rate_floor": 0.54,
            "historical_oos_already_observed": True,
            "historical_oos_can_promote_new_candidates": False,
            "forward_shadow_start": _forward_shadow_start(),
            "forward_shadow_mode": FORWARD_SHADOW_MODE,
            "forward_shadow_min_trading_days": FORWARD_SHADOW_MIN_TRADING_DAYS,
            "forward_shadow_signals_immutable": True,
            "research_data_latest_offset_trading_days": DIAGNOSTIC_HOLDOUT_DAYS,
            "recent_60d_diagnostic_cannot_select_or_tune": True,
            "boundary_crossing_trades_excluded": True,
        },
        "strategy_sources": {
            "user_supplied_study_materials_20260811": {
                "status": "preregistered_candidate_only",
                "scoring_policy": "python_hard_calculation_ai_not_used_in_score",
                "candidates": [
                    "study_monthly_ma_volume",
                    "study_pa_breakout_followthrough",
                    "study_pa_second_entry_pullback",
                    "study_pa_range_edge_reversal",
                ],
                "rules": [
                    "5_10_20_ma_all_rising_with_volume",
                    "strong_breakout_requires_next_bar_followthrough",
                    "trend_pullback_requires_separated_second_test_and_confirmation",
                    "range_long_only_requires_lower_edge_failed_breakout",
                    "signal_at_close_entry_next_open_T_plus_1",
                ],
                "subjective_concepts_excluded": [
                    "institutional_intent_narrative",
                    "unobservable_trapped_trader_claims",
                    "hand_drawn_AB_CD_anchor_selection",
                    "fixed_60_or_80_percent_probability_claims",
                ],
            },
            "tickflow_stock_panel": [
                "trend_breakout", "bullish_alignment", "macd_golden",
                "volume_price_surge", "low_volatility_leader", "pullback_ma20_bounce",
            ],
            "adaptation": "仅迁移信号思想；统一使用本系统的T+1、成本、非重叠和冻结样本外协议",
            "public_research": {
                "moskowitz_ooi_pedersen_2012": {
                    "title": "Time Series Momentum",
                    "url": "https://www.aqr.com/Insights/Datasets/Time-Series-Momentum-Original-Paper-Data",
                    "rule_transfer": "12个月收益跳过最近1个月，正值做多，持有约1个月",
                    "applicability_warning": "原论文覆盖期货与远期，不直接证明A股个股有效",
                },
                "baker_bradley_wurgler_2011": {
                    "title": "Benchmarks as Limits to Arbitrage: Understanding the Low-Volatility Anomaly",
                    "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1585031",
                    "status": "existing_low_volatility_lane",
                },
                "asness_frazzini_pedersen_quality": {
                    "title": "Quality Minus Junk",
                    "url": "https://conference.nber.org/confer/2013/BEf13/Frazzini_Pedersen_Asness.pdf",
                    "status": "blocked_until_point_in_time_full_financial_factors",
                },
            },
        },
        "limitations": [
            "未模拟逐股涨跌停无法成交",
            "未模拟冲击成本和分红税",
            "本轮只允许预先声明的有限候选，防止无限调参过拟合",
            "前向影子使用最近60个交易日真实行情回放冻结候选；满窗后只评估一次",
            "价格行为材料中的主观画线已转换为冻结代理规则，历史诊断不能证明其有效",
        ],
    }
    _write(run_root / "result.json", payload)
    _write(latest_path, payload)
    if passed:
        _write(root / "champion.json", payload)
    _write(root / "status.json", {key: payload[key] for key in ("status", "run_id", "updated_at", "decision", "promotion_passed")})
    return payload


if __name__ == "__main__":
    run_strategy_iteration()
