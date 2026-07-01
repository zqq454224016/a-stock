"""Cron 调度运行器。"""

from __future__ import annotations

import signal
import sys

from quant_system.config.schedule_config import ScheduleConfig
from quant_system.tasks.backfill_job import run_backfill
from quant_system.tasks.daily_job import run_daily_market
from quant_system.tasks.intraday_job import run_intraday_snapshot
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)

JOB_MAP = {
    "daily_market": lambda: run_daily_market(mock=False),
    "daily_stock": lambda: run_daily_stock(),
    "intraday_snapshot": run_intraday_snapshot,
}


def run_job(name: str) -> None:
    fn = JOB_MAP.get(name)
    if not fn:
        raise ValueError(f"未知任务: {name}")
    logger.info("执行任务: %s", name)
    fn()


def start_scheduler() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("请安装 apscheduler: pip install apscheduler")
        sys.exit(1)

    cfg = ScheduleConfig()
    scheduler = BlockingScheduler()

    cron_jobs = {
        "daily_market": cfg.daily_market,
        "daily_stock": cfg.daily_stock,
        "intraday_snapshot": cfg.intraday_snapshot,
    }

    for name, cron_expr in cron_jobs.items():
        if name not in cfg.enabled_jobs:
            continue
        parts = cron_expr.split()
        if len(parts) != 5:
            logger.warning("无效 cron: %s", cron_expr)
            continue
        minute, hour, day, month, day_of_week = parts
        scheduler.add_job(
            run_job, CronTrigger(
                minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week,
            ),
            args=[name], id=name, replace_existing=True,
        )
        logger.info("已注册调度: %s -> %s", name, cron_expr)

    def shutdown(signum, frame):
        logger.info("收到退出信号，停止调度器")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("调度器启动，Ctrl+C 退出")
    scheduler.start()
