"""Pipeline orchestration helpers."""

from __future__ import annotations

from quant_system.apps.reports import (
    generate_agent_dashboard,
    generate_attribution_report,
    generate_backtest_reports,
    generate_console_report,
    generate_decision_report,
    generate_enhance_reports,
    generate_factor_reports,
    generate_impact_report,
    generate_live_dashboard,
    generate_monitoring_report,
    generate_portfolio_report,
    generate_predict_reports,
    generate_reports,
    generate_review_report,
    generate_selector_report,
    generate_trading_report,
    sync_report_index_hubs,
)
from quant_system.tasks.agent_job import run_agent_job
from quant_system.tasks.attribution_job import run_attribution_job
from quant_system.tasks.backtest_job import run_backtest_job
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.decision_job import run_decision_job
from quant_system.tasks.enhance_job import run_enhance_job
from quant_system.tasks.factor_job import run_factor_compute
from quant_system.tasks.impact_job import run_impact_job
from quant_system.tasks.intraday_job import run_intraday_live
from quant_system.tasks.inspect_job import run_data_inspect
from quant_system.tasks.monitoring_job import run_monitoring_job
from quant_system.tasks.predict_job import run_predict_job
from quant_system.tasks.portfolio_job import run_portfolio_job
from quant_system.tasks.review_job import run_review_job
from quant_system.tasks.selector_job import run_selector_job
from quant_system.tasks.sentiment_job import run_sentiment_job
from quant_system.tasks.sim_trade_job import run_sim_trade_job
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.utils.logger import get_logger
from quant_system.utils.watchlist_utils import ensure_watchlist_history

logger = get_logger("apps.pipeline")


def run_mvp_pipeline(*, skip_inspect: bool = False, skip_sentiment: bool = False) -> None:
    """MVP 闭环：数据 → 因子 → 回测 → 预测 → 报表（Quantification.md §1.3）。"""
    from quant_system.config.crawler_config import CrawlerConfig

    cfg = CrawlerConfig()
    logger.info("=== MVP 闭环开始（历史窗口 %s 日）===", cfg.mvp_hist_days)

    if not skip_inspect:
        run_data_inspect(auto_fix=True)
    ensure_watchlist_history(min_days=cfg.mvp_hist_days)
    run_daily_market(mock=False)
    run_daily_stock()
    if not skip_sentiment:
        run_sentiment_job()
    run_enhance_job()
    run_factor_compute()
    run_intraday_live()
    run_backtest_job(days=cfg.mvp_hist_days, allow_warn_quality=True)
    generate_backtest_reports()
    run_predict_job(allow_warn_quality=True, auto_backtest=True)
    generate_predict_reports()
    run_impact_job()
    generate_impact_report()
    run_selector_job(auto_predict=False)
    generate_selector_report()
    run_decision_job(auto_predict=False)
    generate_decision_report()
    run_sim_trade_job(auto_predict=False)
    generate_trading_report()
    run_portfolio_job()
    generate_portfolio_report()
    run_review_job()
    generate_review_report()
    run_attribution_job()
    generate_attribution_report()
    generate_reports()
    generate_factor_reports()
    generate_enhance_reports()
    generate_live_dashboard()
    run_agent_job()
    generate_agent_dashboard()
    generate_console_report()
    run_monitoring_job()
    generate_monitoring_report()
    sync_report_index_hubs()
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

    if not skip_inspect:
        run_data_inspect(auto_fix=True)
    ensure_watchlist_history(min_days=CrawlerConfig().mvp_hist_days)
    run_daily_market(mock=False)
    run_daily_stock()
    if not skip_sentiment:
        run_sentiment_job()
    if not skip_enhance:
        run_enhance_job()
    run_factor_compute()
    run_intraday_live()
    if not skip_backtest:
        run_backtest_job(allow_warn_quality=True)
        generate_backtest_reports()
    if not skip_predict:
        run_predict_job(allow_warn_quality=True, auto_backtest=not skip_backtest)
        generate_predict_reports()
        run_impact_job()
        generate_impact_report()
        run_selector_job(auto_predict=False)
        generate_selector_report()
        run_decision_job(auto_predict=False)
        generate_decision_report()
        run_sim_trade_job(auto_predict=False)
        generate_trading_report()
        run_portfolio_job()
        generate_portfolio_report()
        run_review_job()
        generate_review_report()
        run_attribution_job()
        generate_attribution_report()
    generate_reports()
    generate_factor_reports()
    generate_enhance_reports()
    generate_live_dashboard()
    run_agent_job()
    generate_agent_dashboard()
    generate_console_report()
    run_monitoring_job()
    generate_monitoring_report()
    sync_report_index_hubs()
