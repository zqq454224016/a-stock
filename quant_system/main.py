#!/usr/bin/env python3
"""量化系统启动入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 确保项目根目录在 PYTHONPATH
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_system.scheduler.cron_runner import run_job, start_scheduler
from quant_system.monitoring.task_runs import TaskRunRecorder
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
from quant_system.utils.watchlist_utils import ensure_watchlist_history, ensure_watchlist_stocks, resolve_codes

logger = get_logger("main")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="A股量化数据采集系统")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("scheduler", help="启动定时调度器")

    market = sub.add_parser("market", help="采集大盘行情")
    market.add_argument("--mock", action="store_true", help="使用已有 JSON 数据")

    stock = sub.add_parser("stock", help="采集自选股分析")
    stock.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    live = sub.add_parser("live", help="盘中实时采集（分钟线+实时价）")
    live.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    live.add_argument("--loop", action="store_true", help="循环采集直到 Ctrl+C")
    live.add_argument("--interval", type=int, default=60, help="循环间隔秒数")

    factor = sub.add_parser("factor", help="计算自选股技术因子")
    factor.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    factor.add_argument("--force", action="store_true", help="忽略质量门禁")
    sub.add_parser("factor-eval", help="因子有效性评估（相关性、分层收益、漂移）")

    inspect = sub.add_parser("inspect", help="K 线质量巡检")
    inspect.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    inspect.add_argument("--fix", action="store_true", help="发现问题时自动 backfill")
    inspect.add_argument("--lookback", type=int, default=60, help="缺口检测窗口（自然日）")

    backfill = sub.add_parser("backfill", help="补录历史 K 线")
    backfill.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    backfill.add_argument("--days", type=int, default=250)
    backfill.add_argument("--no-refresh", action="store_true", help="仅写 backfill/ 归档，不刷新 stocks")

    run = sub.add_parser("run", help="执行单个调度任务")
    run.add_argument("job", choices=[
        "daily_market", "daily_stock", "intraday_snapshot",
        "data_inspect", "factor_compute", "backfill_weekly",
    ])

    all_cmd = sub.add_parser("all", help="inspect → market → stock → 回测 → 预测 → 报表")
    all_cmd.add_argument("--skip-inspect", action="store_true", help="跳过质量巡检")
    all_cmd.add_argument("--skip-backtest", action="store_true", help="跳过回测")
    all_cmd.add_argument("--skip-predict", action="store_true", help="跳过走势预测")
    all_cmd.add_argument("--skip-sentiment", action="store_true", help="跳过舆情采集")
    all_cmd.add_argument("--skip-enhance", action="store_true", help="跳过数据增强")
    sub.add_parser("mvp", help="MVP 闭环（同 all，含 750 日补录 + 盘中看板 + 舆情）")

    sent = sub.add_parser("sentiment", help="舆情采集（东财评论 + 雪球热榜）")
    sent.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    enhance = sub.add_parser("enhance", help="数据增强（估值/公司行为/资金/指数）")
    enhance.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    impact = sub.add_parser("impact", help="实际影响数据提取（业绩/估值/解禁/材料价格）")
    impact.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    attribution = sub.add_parser("attribution", help="每日涨跌归因（昨日/今日对比）")
    attribution.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    agent = sub.add_parser("agent", help="Agent 分析（选股解释/策略诊断/预测复盘）")
    agent.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    agent.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    agent.add_argument("--provider", default="rule", choices=["rule", "llm"], help="Agent Provider，llm 未配置时自动降级")

    decision = sub.add_parser("decision", help="单股指导性操作建议（高指导性、低实时性）")
    decision.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    decision.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    decision.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    decision.add_argument("--no-agent", action="store_true", help="缺少 Agent 报告时不自动生成")
    decision.add_argument("--no-impact", action="store_true", help="缺少实际影响数据时不自动生成")

    selector = sub.add_parser("selector", help="上涨候选池筛选与排名")
    selector.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    selector.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    selector.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    selector.add_argument("--no-impact", action="store_true", help="缺少实际影响数据时不自动生成")

    sim = sub.add_parser("simtrade", help="模拟交易（P3-1，基于决策/预测虚拟调仓）")
    sim.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    sim.add_argument("--reset", action="store_true", help="重置虚拟账户")
    sim.add_argument("--cash", type=float, default=None, help="重置时使用的初始资金")
    sim.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    sim.add_argument("--no-decision", action="store_true", help="缺少决策时不自动生成")

    sub.add_parser("portfolio", help="组合管理与账户级风控")
    sub.add_parser("console", help="统一 Web 控制台")
    sub.add_parser("monitor", help="监控告警与数据血缘")
    sub.add_parser("registry", help="数据产物注册表")
    sub.add_parser("v3-plan", help="v3 稳定化与扩展路线")

    bt = sub.add_parser("backtest", help="单策略日线回测（MA金叉）")
    bt.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    bt.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"], help="策略名称")
    bt.add_argument("--days", type=int, default=750, help="回测 K 线天数（约3年=750）")
    bt.add_argument("--cash", type=float, default=100_000, help="初始资金")
    bt.add_argument("--allow-warn", action="store_true", help="允许质量分 70-89 进入回测")
    bt.add_argument("--no-rolling", action="store_true", help="跳过滚动样本外验证")

    pred = sub.add_parser("predict", help="可验证走势预测（5d 方向/概率/置信度）")
    pred.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    pred.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    pred.add_argument("--horizon", default="5d", choices=["1d", "5d", "20d"])
    pred.add_argument("--days", type=int, default=750)
    pred.add_argument("--no-backtest", action="store_true", help="不自动补跑回测")
    pred.add_argument("--allow-warn", action="store_true")

    replay = sub.add_parser("replay", help="十日前视角滚动推演（无未来函数复盘）")
    replay.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    replay.add_argument("--days", type=int, default=10, help="向前回放的交易日数量")

    review = sub.add_parser("review", help="后验复盘（预测/候选/决策 1/5/20 日收益）")
    review.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    recommend = sub.add_parser("recommend", help="短线、中线、长线股票推荐")
    recommend.add_argument("--limit", type=int, default=5, help="每个周期最多推荐数量")
    sub.add_parser("framework", help="模块化算法框架契约快照")

    return p


def generate_predict_reports() -> None:
    import subprocess
    path = ROOT / "script/gen_predict_report.py"
    if path.exists():
        logger.info("生成预测报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_backtest_reports() -> None:
    import subprocess
    path = ROOT / "script/gen_backtest_report.py"
    if path.exists():
        logger.info("生成回测报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_factor_reports() -> None:
    import subprocess
    path = ROOT / "script" / "gen_factor_report.py"
    if path.exists():
        logger.info("生成因子排名: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_factor_eval_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_factor_eval_report.py"
    if path.exists():
        logger.info("生成因子有效性报告: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_recommendation_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_recommendation_report.py"
    if path.exists():
        logger.info("生成多周期推荐报告: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_framework_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_framework_report.py"
    if path.exists():
        logger.info("生成模块化框架报告: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_console_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_console_report.py"
    if path.exists():
        logger.info("生成统一控制台: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_monitoring_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_monitoring_report.py"
    if path.exists():
        logger.info("生成监控告警报告: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_v3_roadmap_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_v3_roadmap_report.py"
    if path.exists():
        logger.info("生成 v3 路线报告: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_live_dashboard() -> None:
    import subprocess
    path = ROOT / "script" / "gen_live_dashboard.py"
    if path.exists():
        logger.info("生成盘中看板: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_enhance_reports() -> None:
    import subprocess
    path = ROOT / "script" / "gen_enhance_report.py"
    if path.exists():
        logger.info("生成数据增强报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_agent_dashboard() -> None:
    import subprocess
    path = ROOT / "script" / "gen_agent_dashboard.py"
    if path.exists():
        logger.info("生成 Agent 看板: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_trading_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_trading_report.py"
    if path.exists():
        logger.info("生成模拟交易报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_portfolio_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_portfolio_report.py"
    if path.exists():
        logger.info("生成组合管理报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_decision_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_decision_report.py"
    if path.exists():
        logger.info("生成决策报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_impact_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_impact_report.py"
    if path.exists():
        logger.info("生成实际影响数据报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_attribution_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_attribution_report.py"
    if path.exists():
        logger.info("生成每日归因报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_selector_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_selector_report.py"
    if path.exists():
        logger.info("生成上涨候选池报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_replay_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_replay_report.py"
    if path.exists():
        logger.info("生成历史推演报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def generate_review_report() -> None:
    import subprocess
    path = ROOT / "script" / "gen_review_report.py"
    if path.exists():
        logger.info("生成后验复盘报表: %s", path.name)
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def sync_report_index_hubs() -> None:
    import subprocess
    path = ROOT / "script" / "report_index_utils.py"
    if path.exists():
        subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


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


def generate_reports(stock_only: bool = False) -> None:
    """调用现有 HTML 报表生成脚本；生成前补齐 watchlist 缺失个股。"""
    ensure_watchlist_stocks()
    import subprocess
    scripts = ("script/gen_stock_report.py",) if stock_only else (
        "script/gen_report.py", "script/gen_stock_report.py",
    )
    for script in scripts:
        path = ROOT / script
        if path.exists():
            logger.info("生成报表: %s", script)
            subprocess.run([sys.executable, str(path)], check=False, cwd=ROOT)


def _execute(args: argparse.Namespace) -> None:
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
        if not args.skip_inspect:
            run_data_inspect(auto_fix=True)
        from quant_system.config.crawler_config import CrawlerConfig
        ensure_watchlist_history(min_days=CrawlerConfig().mvp_hist_days)
        run_daily_market(mock=False)
        run_daily_stock()
        if not args.skip_sentiment:
            run_sentiment_job()
        if not args.skip_enhance:
            run_enhance_job()
        run_factor_compute()
        run_intraday_live()
        if not args.skip_backtest:
            run_backtest_job(allow_warn_quality=True)
            generate_backtest_reports()
        if not args.skip_predict:
            run_predict_job(allow_warn_quality=True, auto_backtest=not args.skip_backtest)
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
    else:
        build_parser().print_help()


def main() -> None:
    args = build_parser().parse_args()
    command = args.command or "help"
    recorder = TaskRunRecorder(command=command, argv=sys.argv[1:])
    recorder.start()
    try:
        _execute(args)
    except SystemExit as exc:
        status = "success" if exc.code in (0, None) else "failed"
        recorder.finish(status=status, error=exc if status == "failed" else None)
        raise
    except BaseException as exc:
        recorder.finish(status="failed", error=exc)
        raise
    else:
        status = "skipped" if command == "help" else "success"
        recorder.finish(status=status)


if __name__ == "__main__":
    main()
