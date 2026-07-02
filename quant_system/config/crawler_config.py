"""爬虫与数据源配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from quant_system.config.mvp_config import MVP_DISPLAY_DAYS, MVP_HIST_DAYS

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class CrawlerConfig:
    # 数据源优先级：sina（推荐，东财易断连）| eastmoney | auto（先东财后降级）
    prefer_source: str = os.getenv("CRAWLER_PREFER_SOURCE", "sina")
    retry_times: int = 3
    retry_delay: float = 2.0
    eastmoney_probe_retries: int = 1  # 探测东财时的重试次数（auto 模式）
    request_timeout: int = 30
    stock_hist_days: int = MVP_DISPLAY_DAYS
    mvp_hist_days: int = MVP_HIST_DAYS
    cross_source_check: bool = os.getenv("CRAWLER_CROSS_SOURCE", "1") != "0"
    cross_source_lookback: int = 20
    industry_top_n: int = 20
    rank_top_n: int = 10
    minute_bars_1m: int = 120
    live_redis_ttl: int = 300
    live_refresh_sec: int = 15

    data_dir: Path = PROJECT_ROOT / "assets" / "data"
    stock_data_dir: Path = PROJECT_ROOT / "assets" / "data" / "stocks"
    watchlist_file: Path = PROJECT_ROOT / "assets" / "data" / "watchlist.json"
    latest_file: Path = PROJECT_ROOT / "assets" / "data" / "latest.json"

    index_map_em: dict[str, str] = field(default_factory=lambda: {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000688": "科创50",
        "899050": "北证50",
    })

    index_map_sina: dict[str, tuple[str, str]] = field(default_factory=lambda: {
        "sh000001": ("000001", "上证指数"),
        "sz399001": ("399001", "深证成指"),
        "sz399006": ("399006", "创业板指"),
        "sh000688": ("000688", "科创50"),
        "bj899050": ("899050", "北证50"),
    })

    distribution_colors: dict[str, str] = field(default_factory=lambda: {
        "涨停": "#dc2626",
        "涨幅>5%": "#ef4444",
        "涨幅0~5%": "#f87171",
        "平盘": "#6b7280",
        "跌幅0~5%": "#4ade80",
        "跌幅>5%": "#22c55e",
        "跌停": "#16a34a",
    })
