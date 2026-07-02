"""任务调度配置。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScheduleConfig:
    """cron 表达式（标准 5 段）。"""

    daily_market: str = "30 18 * * 1-5"      # 工作日 18:30
    daily_stock: str = "45 18 * * 1-5"       # 工作日 18:45
    intraday_snapshot: str = "*/1 9-15 * * 1-5"   # 盘中每 1 分钟
    backfill_weekly: str = "0 2 * * 0"       # 周日 02:00 补数
    data_inspect: str = "30 2 * * 0"         # 周日 02:30 质量巡检+补数

    enabled_jobs: list[str] = field(default_factory=lambda: [
        "daily_market",
        "daily_stock",
        "intraday_snapshot",
        "data_inspect",
        "backfill_weekly",
    ])
