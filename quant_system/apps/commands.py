"""Command dispatch for the CLI."""

from __future__ import annotations

import argparse

from quant_system.apps.pipeline import run_all_pipeline, run_mvp_pipeline
from quant_system.scheduler.cron_runner import run_job, start_scheduler
from quant_system.tasks.agent_job import run_agent_job
from quant_system.tasks.attribution_job import run_attribution_job
from quant_system.tasks.backfill_job import run_backfill
from quant_system.tasks.backtest_job import run_backtest_job
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.decision_job import run_decision_job
from quant_system.tasks.diagnosis_job import run_diagnosis_job
from quant_system.tasks.enhance_job import run_enhance_job
from quant_system.tasks.factor_eval_job import run_factor_eval_job
from quant_system.tasks.factor_job import run_factor_compute
from quant_system.tasks.framework_job import run_framework_job
from quant_system.tasks.impact_job import run_impact_job
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
from quant_system.utils.logger import get_logger
from quant_system.pipeline.normalizer import normalize_code

logger = get_logger("apps.commands")


def resolve_codes(codes: list[str] | None) -> list[str]:
    """Normalize only codes explicitly supplied by the caller."""
    return list(dict.fromkeys(normalize_code(code) for code in (codes or []) if code))


def execute_command(args: argparse.Namespace) -> None:
    from quant_system.apps.cli import build_parser

    if args.command == "scheduler":
        start_scheduler()
    elif args.command == "market":
        run_daily_market(mock=args.mock)
    elif args.command == "stock":
        run_daily_stock(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "diagnose":
        run_diagnosis_job(codes=resolve_codes(args.codes) if args.codes else None, focus=args.focus)
    elif args.command == "config":
        from quant_system.config.app_config import save_data_source_config
        if all(value is None for value in (
            args.tickflow_key, args.tickflow_base_url, args.tushare_token, args.feishu_webhook,
        )):
            raise ValueError("至少提供一个配置项")
        path = save_data_source_config(
            tickflow_api_key=args.tickflow_key,
            tickflow_base_url=args.tickflow_base_url,
            tushare_token=args.tushare_token,
            feishu_webhook_url=args.feishu_webhook,
        )
        logger.info("数据源配置已写入 %s", path)
    elif args.command == "serve":
        from quant_system.web.server import serve
        serve(host=args.host, port=args.port)
    elif args.command == "mvp":
        run_mvp_pipeline(skip_inspect=False)
    elif args.command == "sentiment":
        run_sentiment_job(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "enhance":
        run_enhance_job(codes=resolve_codes(args.codes) if args.codes else None)
        run_factor_compute(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "impact":
        run_impact_job(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "attribution":
        run_attribution_job(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "agent":
        run_agent_job(codes=resolve_codes(args.codes) if args.codes else None, strategy=args.strategy, provider=args.provider)
    elif args.command == "decision":
        run_decision_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy=args.strategy,
            auto_predict=not args.no_predict,
            auto_agent=not args.no_agent,
            auto_impact=not args.no_impact,
        )
    elif args.command == "selector":
        run_selector_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy=args.strategy,
            auto_predict=not args.no_predict,
            auto_impact=not args.no_impact,
        )
    elif args.command == "simtrade":
        run_sim_trade_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            reset=args.reset,
            auto_predict=not args.no_predict,
            auto_decision=not args.no_decision,
            initial_cash=args.cash,
        )
    elif args.command == "portfolio":
        run_portfolio_job()
    elif args.command == "factor":
        run_factor_compute(codes=resolve_codes(args.codes) if args.codes else None, ignore_quality=args.force)
    elif args.command == "factor-eval":
        run_factor_eval_job()
    elif args.command == "inspect":
        run_data_inspect(
            codes=resolve_codes(args.codes) if args.codes else None,
            auto_fix=args.fix,
            lookback_days=args.lookback,
        )
    elif args.command == "backfill":
        codes = resolve_codes(args.codes)
        if not codes:
            raise ValueError("backfill 必须显式提供股票代码")
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
    elif args.command == "predict":
        run_predict_job(
            codes=resolve_codes(args.codes) if args.codes else None,
            strategy_name=args.strategy,
            horizon=args.horizon,
            days=args.days,
            auto_backtest=not args.no_backtest,
            allow_warn_quality=args.allow_warn,
        )
    elif args.command == "replay":
        run_replay_job(codes=resolve_codes(args.codes) if args.codes else None, days=args.days)
    elif args.command == "review":
        run_review_job(codes=resolve_codes(args.codes) if args.codes else None)
    elif args.command == "recommend":
        run_recommendation_job(limit=max(1, min(args.limit, 20)))
    elif args.command == "framework":
        run_framework_job()
    elif args.command == "monitor":
        run_monitoring_job()
    elif args.command == "registry":
        run_registry_job()
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
