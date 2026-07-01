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
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.intraday_job import run_intraday_live, run_intraday_loop
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.utils.logger import get_logger

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

    backfill = sub.add_parser("backfill", help="补录历史 K 线")
    backfill.add_argument("codes", nargs="+", help="股票代码")
    backfill.add_argument("--days", type=int, default=250)

    run = sub.add_parser("run", help="执行单个调度任务")
    run.add_argument("job", choices=["daily_market", "daily_stock", "intraday_snapshot"])

    sub.add_parser("all", help="依次执行 market + stock + 生成报表")

    return p


def generate_reports(stock_only: bool = False) -> None:
    """调用现有 HTML 报表生成脚本。"""
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
        run_daily_stock(codes=args.codes or None)
        generate_reports(stock_only=True)
    elif args.command == "live":
        if args.loop:
            run_intraday_loop(interval_sec=args.interval, codes=args.codes or None)
        else:
            run_intraday_live(codes=args.codes or None)
    elif args.command == "backfill":
        run_backfill(args.codes, days=args.days)
    elif args.command == "run":
        run_job(args.job)
    elif args.command == "all":
        run_daily_market(mock=False)
        run_daily_stock()
        generate_reports()
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
