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
from quant_system.tasks.backfill_job import run_backfill
from quant_system.tasks.backtest_job import run_backtest_job
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.factor_job import run_factor_compute
from quant_system.tasks.intraday_job import run_intraday_live, run_intraday_loop
from quant_system.tasks.inspect_job import run_data_inspect
from quant_system.tasks.predict_job import run_predict_job
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.utils.logger import get_logger
from quant_system.utils.watchlist_utils import ensure_watchlist_stocks, resolve_codes

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

    bt = sub.add_parser("backtest", help="单策略日线回测（MA金叉）")
    bt.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    bt.add_argument("--strategy", default="ma_cross", choices=["ma_cross"], help="策略名称")
    bt.add_argument("--days", type=int, default=750, help="回测 K 线天数（约3年=750）")
    bt.add_argument("--cash", type=float, default=100_000, help="初始资金")
    bt.add_argument("--allow-warn", action="store_true", help="允许质量分 70-89 进入回测")

    pred = sub.add_parser("predict", help="可验证走势预测（5d 方向/概率/置信度）")
    pred.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    pred.add_argument("--strategy", default="ma_cross", choices=["ma_cross"])
    pred.add_argument("--horizon", default="5d", choices=["1d", "5d", "20d"])
    pred.add_argument("--days", type=int, default=750)
    pred.add_argument("--no-backtest", action="store_true", help="不自动补跑回测")
    pred.add_argument("--allow-warn", action="store_true")

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


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "scheduler":
        start_scheduler()
    elif args.command == "market":
        run_daily_market(mock=args.mock)
    elif args.command == "stock":
        run_daily_stock(codes=resolve_codes(args.codes))
        run_intraday_live(codes=resolve_codes(args.codes))
        generate_reports(stock_only=True)
    elif args.command == "live":
        if args.loop:
            run_intraday_loop(interval_sec=args.interval, codes=resolve_codes(args.codes))
        else:
            run_intraday_live(codes=resolve_codes(args.codes))
    elif args.command == "factor":
        run_factor_compute(codes=resolve_codes(args.codes), ignore_quality=args.force)
    elif args.command == "inspect":
        run_data_inspect(
            codes=resolve_codes(args.codes),
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
            codes=resolve_codes(args.codes),
            strategy_name=args.strategy,
            days=args.days,
            allow_warn_quality=args.allow_warn,
            initial_cash=args.cash,
        )
        generate_backtest_reports()
    elif args.command == "predict":
        run_predict_job(
            codes=resolve_codes(args.codes),
            strategy_name=args.strategy,
            horizon=args.horizon,
            days=args.days,
            auto_backtest=not args.no_backtest,
            allow_warn_quality=args.allow_warn,
        )
        generate_predict_reports()
    elif args.command == "run":
        run_job(args.job)
    elif args.command == "all":
        if not args.skip_inspect:
            run_data_inspect(auto_fix=True)
        run_daily_market(mock=False)
        run_daily_stock()  # 完整 watchlist
        run_intraday_live()  # 刷新盘中 live JSON（现价 + 分钟线）
        if not args.skip_backtest:
            run_backtest_job(allow_warn_quality=True)
            generate_backtest_reports()
        if not args.skip_predict:
            run_predict_job(allow_warn_quality=True, auto_backtest=not args.skip_backtest)
            generate_predict_reports()
        generate_reports()
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
