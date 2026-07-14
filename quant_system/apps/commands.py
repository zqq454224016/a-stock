"""Command dispatch for the CLI."""

from __future__ import annotations

import argparse
import sys

from quant_system.apps.pipeline import run_all_pipeline, run_mvp_pipeline
from quant_system.apps.reports import (
    generate_agent_dashboard,
    generate_attribution_report,
    generate_backtest_reports,
    generate_console_report,
    generate_decision_report,
    generate_enhance_reports,
    generate_factor_eval_report,
    generate_factor_reports,
    generate_framework_report,
    generate_impact_report,
    generate_live_dashboard,
    generate_monitoring_report,
    generate_portfolio_report,
    generate_predict_reports,
    generate_recommendation_report,
    generate_replay_report,
    generate_reports,
    generate_review_report,
    generate_selector_report,
    generate_trading_report,
    generate_v3_roadmap_report,
    sync_report_index_hubs,
)
from quant_system.scheduler.cron_runner import run_job, start_scheduler
from quant_system.tasks.agent_job import run_agent_job
from quant_system.tasks.attribution_job import run_attribution_job
from quant_system.tasks.backfill_job import run_backfill
from quant_system.tasks.backtest_job import run_backtest_job
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.decision_job import run_decision_job
from quant_system.tasks.enhance_job import run_enhance_job
from quant_system.tasks.factor_eval_job import run_factor_eval_job
from quant_system.tasks.factor_job import run_factor_compute
from quant_system.tasks.framework_job import run_framework_job
from quant_system.tasks.impact_job import run_impact_job
from quant_system.tasks.intraday_job import run_intraday_live, run_intraday_loop
from quant_system.tasks.inspect_job import run_data_inspect
from quant_system.tasks.monitoring_job import run_monitoring_job
from quant_system.tasks.predict_job import run_predict_job
from quant_system.tasks.portfolio_job import run_portfolio_job
from quant_system.tasks.replay_job import run_replay_job
from quant_system.tasks.recommendation_job import run_recommendation_job
from quant_system.tasks.registry_job import run_registry_job
from quant_system.tasks.review_job import run_review_job
from quant_system.tasks.selector_job import run_selector_job
from quant_system.tasks.sentiment_job import run_sentiment_job
from quant_system.tasks.sim_trade_job import run_sim_trade_job
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.tasks.v3_plan_job import run_v3_plan_job
from quant_system.utils.logger import get_logger
from quant_system.utils.watchlist_utils import resolve_codes

logger = get_logger("apps.commands")


def execute_command(args: argparse.Namespace) -> None:
    from quant_system.apps.cli import build_parser

    if args.command == "scheduler":
        start_scheduler()
    elif args.command == "market":
        run_daily_market(mock=args.mock)
    elif args.command == "stock":
        run_daily_stock(codes=resolve_codes(args.codes))
        run_intraday_live(codes=resolve_codes(args.codes))
        generate_live_dashboard()
        generate_reports(stock_only=True)
    elif args.command == "live":
        if args.loop:
            run_intraday_loop(interval_sec=args.interval, codes=resolve_codes(args.codes))
        else:
            run_intraday_live(codes=resolve_codes(args.codes))
            generate_live_dashboard()
    elif args.command == "mvp":
        run_mvp_pipeline(skip_inspect=False)
    elif args.command == "sentiment":
        run_sentiment_job(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "enhance":
        run_enhance_job(codes=resolve_codes(args.codes) if args.codes else None)
        run_factor_compute(codes=resolve_codes(args.codes) if args.codes else None)
        generate_enhance_reports()
        generate_factor_reports()
        generate_reports(stock_only=True)
    elif args.command == "impact":
        run_impact_job(codes=resolve_codes(args.codes) if args.codes else None)
        generate_impact_report()
        sync_report_index_hubs()
    elif args.command == "attribution":
        run_attribution_job(codes=resolve_codes(args.codes) if args.codes else None)
        generate_attribution_report()
        sync_report_index_hubs()
    elif args.command == "agent":
        run_agent_job(codes=resolve_codes(args.codes) if args.codes else None, strategy=args.strategy, provider=args.provider)
        generate_agent_dashboard()
    elif args.command == "decision":
        run_decision_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy=args.strategy,
            auto_predict=not args.no_predict,
            auto_agent=not args.no_agent,
            auto_impact=not args.no_impact,
        )
        generate_decision_report()
        sync_report_index_hubs()
    elif args.command == "selector":
        run_selector_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy=args.strategy,
            auto_predict=not args.no_predict,
            auto_impact=not args.no_impact,
        )
        generate_selector_report()
        sync_report_index_hubs()
    elif args.command == "simtrade":
        run_sim_trade_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            reset=args.reset,
            auto_predict=not args.no_predict,
            auto_decision=not args.no_decision,
            initial_cash=args.cash,
        )
        generate_trading_report()
        sync_report_index_hubs()
    elif args.command == "portfolio":
        run_portfolio_job()
        generate_portfolio_report()
        sync_report_index_hubs()
    elif args.command == "factor":
        run_factor_compute(codes=resolve_codes(args.codes) if args.codes else None, ignore_quality=args.force)
    elif args.command == "factor-eval":
        run_factor_eval_job()
        generate_factor_eval_report()
        sync_report_index_hubs()
    elif args.command == "inspect":
        run_data_inspect(
            codes=resolve_codes(args.codes) if args.codes else None,
            auto_fix=args.fix,
            lookback_days=args.lookback,
        )
    elif args.command == "backfill":
        codes = resolve_codes(args.codes)
        if not codes:
            logger.error("watchlist 为空，请编辑 assets/data/watchlist.json")
            sys.exit(1)
        run_backfill(codes, days=args.days, refresh_stocks=not args.no_refresh)
    elif args.command == "backtest":
        run_backtest_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy_name=args.strategy,
            days=args.days,
            allow_warn_quality=args.allow_warn,
            initial_cash=args.cash,
            rolling=not args.no_rolling,
        )
        generate_backtest_reports()
    elif args.command == "predict":
        run_predict_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy_name=args.strategy,
            horizon=args.horizon,
            days=args.days,
            auto_backtest=not args.no_backtest,
            allow_warn_quality=args.allow_warn,
        )
        generate_predict_reports()
    elif args.command == "replay":
        run_replay_job(codes=resolve_codes(args.codes) if args.codes else None, days=args.days)
        generate_replay_report()
        sync_report_index_hubs()
    elif args.command == "review":
        run_review_job(codes=resolve_codes(args.codes) if args.codes else None)
        generate_review_report()
        sync_report_index_hubs()
    elif args.command == "recommend":
        run_recommendation_job(limit=max(1, min(args.limit, 20)))
        generate_recommendation_report()
        sync_report_index_hubs()
    elif args.command == "framework":
        run_framework_job()
        generate_framework_report()
        sync_report_index_hubs()
    elif args.command == "console":
        generate_console_report()
        sync_report_index_hubs()
    elif args.command == "monitor":
        run_monitoring_job()
        generate_monitoring_report()
        sync_report_index_hubs()
    elif args.command == "registry":
        run_registry_job()
    elif args.command == "v3-plan":
        run_v3_plan_job()
        generate_v3_roadmap_report()
        sync_report_index_hubs()
    elif args.command == "run":
        run_job(args.job)
    elif args.command == "all":
        run_all_pipeline(
            skip_inspect=args.skip_inspect,
            skip_backtest=args.skip_backtest,
            skip_predict=args.skip_predict,
            skip_sentiment=args.skip_sentiment,
            skip_enhance=args.skip_enhance,
        )
    else:
        build_parser().print_help()
