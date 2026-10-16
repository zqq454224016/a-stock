"""Pipeline orchestration helpers."""

from __future__ import annotations

from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.factor_job import run_factor_compute
from quant_system.tasks.full_acquisition_job import launch_full_acquisition
from quant_system.tasks.interim_financial_job import run_interim_financial_job
from quant_system.tasks.inspect_job import run_data_inspect
from quant_system.tasks.iteration_job import run_auto_iteration
from quant_system.tasks.monitoring_job import run_monitoring_job
from quant_system.tasks.phase1_market_data_job import run_phase1_market_data
from quant_system.tasks.public_supplement_job import run_public_supplement_job
from quant_system.tasks.recommendation_job import run_recommendation_job
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.tasks.strategy_job import launch_offline_validation, run_trend_strategy_job
from quant_system.tasks.today_change_job import run_today_change_job
from quant_system.tasks.daily_market_recap_job import run_daily_market_recap_job
from quant_system.tasks.daily_filter_intraday_job import run_daily_filter_intraday_job
from quant_system.tasks.sector_data_job import launch_sector_data_job
from quant_system.tasks.sim_trade_job import run_sim_trade_job
from quant_system.tasks.portfolio_job import run_portfolio_job
from quant_system.tasks.realtime_worker import launch_realtime_worker
from quant_system.tasks.polarized_strategy_job import run_polarized_strategy
from quant_system.iteration.worker import launch_iteration_worker
from quant_system.utils.logger import get_logger

logger = get_logger("apps.pipeline")


def run_mvp_pipeline(*, skip_inspect: bool = False, skip_sentiment: bool = False) -> None:
    """MVP 闭环：数据 → 因子 → 回测 → 预测 → 结构化产物。"""
    from quant_system.config.crawler_config import CrawlerConfig

    cfg = CrawlerConfig()
    logger.info("=== MVP 闭环开始（历史窗口 %s 日）===", cfg.mvp_hist_days)

    run_phase1_market_data()
    run_interim_financial_job()
    if not skip_inspect:
        # Full-universe repairs are heavy and belong to the resumable background
        # acquisition worker. The one-command foreground path only audits.
        run_data_inspect(auto_fix=False)
    run_daily_market(mock=False)
    run_public_supplement_job()
    launch_full_acquisition()
    run_factor_compute()
    run_today_change_job()
    run_daily_market_recap_job()
    launch_sector_data_job()
    run_trend_strategy_job()
    run_recommendation_job()
    run_daily_filter_intraday_job()
    run_recommendation_job()
    run_polarized_strategy()
    run_sim_trade_job(auto_predict=False, auto_decision=False)
    run_portfolio_job()
    run_auto_iteration()
    run_monitoring_job()
    launch_offline_validation()
    launch_iteration_worker()
    launch_realtime_worker()
    logger.info("=== MVP 闭环完成 ===")


def run_all_pipeline(
    *,
    skip_inspect: bool = False,
    skip_backtest: bool = False,
    skip_predict: bool = False,
    skip_sentiment: bool = False,
    skip_enhance: bool = False,
) -> None:
    """执行 all 主链路，保留 CLI skip 参数语义。"""
    from quant_system.config.crawler_config import CrawlerConfig

    logger.info("=== 统一流水线开始：基础数据 → 研究 → AI 产物 ===")
    run_phase1_market_data()
    run_interim_financial_job()
    if not skip_inspect:
        # Keep ./run.sh all responsive; launch_full_acquisition below performs
        # resumable repairs in a single background worker.
        run_data_inspect(auto_fix=False)
    run_daily_market(mock=False)
    run_public_supplement_job()
    launch_full_acquisition()
    run_factor_compute()
    run_today_change_job()
    run_daily_market_recap_job()
    launch_sector_data_job()
    run_trend_strategy_job()
    if not skip_predict:
        run_recommendation_job()
        run_daily_filter_intraday_job()
        run_recommendation_job()
        run_polarized_strategy()
        run_sim_trade_job(auto_predict=False, auto_decision=False)
        run_portfolio_job()
    run_auto_iteration()
    run_monitoring_job()
    if not skip_backtest:
        launch_offline_validation()
    launch_iteration_worker()
    launch_realtime_worker()
    logger.info("=== 统一流水线完成 ===")
