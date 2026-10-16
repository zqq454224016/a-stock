"""爬虫与数据源配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from quant_system.config.mvp_config import MVP_DISPLAY_DAYS, MVP_HIST_DAYS
from quant_system.config.app_config import tickflow_config, tushare_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class CrawlerConfig:
    # 主行情源：tickflow（默认）| akshare（兼容回退）
    data_source: str = os.getenv("STOCK_DATA_SOURCE", "tickflow").strip().lower()
    tickflow_api_key: str = field(default_factory=lambda: tickflow_config()["api_key"])
    # 官方 FAQ 支持环境变量覆盖端点，便于延迟测试后快速切换；
    # 未设置时继续读取 config/local.json。
    tickflow_base_url: str = field(default_factory=lambda: os.getenv("TICKFLOW_BASE_URL", "").strip() or tickflow_config()["base_url"])
    tushare_token: str = field(default_factory=lambda: tushare_config()["token"])
    tushare_enabled: bool = os.getenv("TUSHARE_ENABLED", "0") == "1"
    market_status_backfill_days: int = int(os.getenv("MARKET_STATUS_BACKFILL_DAYS", "30"))
    # AkShare 兼容源优先级：auto（先东财后新浪，失败互备）| eastmoney | sina
    prefer_source: str = os.getenv("CRAWLER_PREFER_SOURCE", "auto")
    # 盘后深度模式允许更长等待和更多重试，避免把临时网络缺口误判为数据缺失。
    post_close_deep: bool = os.getenv("POST_CLOSE_DEEP", "0") == "1"
    retry_times: int = 5 if post_close_deep else 3
    retry_delay: float = 3.0 if post_close_deep else 2.0
    eastmoney_probe_retries: int = 1  # 探测东财时的重试次数（auto 模式）
    request_timeout: int = 60 if post_close_deep else 30
    stock_hist_days: int = MVP_DISPLAY_DAYS
    research_hist_days: int = int(os.getenv("RESEARCH_HIST_DAYS", str(2500 if post_close_deep else MVP_HIST_DAYS)))
    mvp_hist_days: int = MVP_HIST_DAYS
    cross_source_check: bool = os.getenv("CRAWLER_CROSS_SOURCE", "1") != "0"
    cross_source_lookback: int = 20
    industry_top_n: int = 20
    rank_top_n: int = 10
    skip_bulk_spot: bool = os.getenv("CRAWLER_SKIP_BULK_SPOT", "0") == "1"  # 强制跳过全市场行情
    fetch_workers: int = int(os.getenv("CRAWLER_FETCH_WORKERS", "2" if post_close_deep else "4"))  # 并发拉取线程数
    # Paid TickFlow daily-K batch: 200 symbols/request, 30 requests/min.
    # Spot quotes: 50 symbols/request, 60/min. Ex-factors: 200/request, 30/min.
    tickflow_batch_size: int = max(1, min(int(os.getenv("TICKFLOW_BATCH_SIZE", "200")), 200))
    tickflow_batch_interval_sec: float = float(os.getenv("TICKFLOW_BATCH_INTERVAL_SEC", "2.1"))
    tickflow_quote_batch_size: int = max(1, min(int(os.getenv("TICKFLOW_QUOTE_BATCH_SIZE", "50")), 50))
    tickflow_quote_interval_sec: float = float(os.getenv("TICKFLOW_QUOTE_INTERVAL_SEC", "1.05"))
    tickflow_ex_factor_batch_size: int = max(1, min(int(os.getenv("TICKFLOW_EX_FACTOR_BATCH_SIZE", "200")), 200))
    tickflow_ex_factor_interval_sec: float = float(os.getenv("TICKFLOW_EX_FACTOR_INTERVAL_SEC", "2.1"))
    # Prefer paid history endpoints when an API key is configured.
    tickflow_use_paid_history: bool = os.getenv("TICKFLOW_USE_PAID_HISTORY", "1") != "0"
    enhance_probe_retries: int = 1  # 增强数据探测重试次数
    disable_eastmoney: bool = os.getenv("CRAWLER_DISABLE_EASTMONEY", "0") == "1"  # 强制跳过东财
    disable_ths: bool = os.getenv("CRAWLER_DISABLE_THS", "0") == "1"  # 强制跳过同花顺
    extra_sources: str = os.getenv("CRAWLER_EXTRA_SOURCES", "ths,xueqiu,tencent")  # 备用行情源
    star_board_reference_only: bool = os.getenv("STAR_BOARD_REFERENCE_ONLY", "1") != "0"
    public_supplement_enabled: bool = os.getenv("PUBLIC_SUPPLEMENT_ENABLED", "1") != "0"
    tencent_quote_batch_size: int = int(os.getenv("TENCENT_QUOTE_BATCH_SIZE", "60"))
    eastmoney_min_interval_sec: float = float(os.getenv("EASTMONEY_MIN_INTERVAL_SEC", "1.2"))
    candidate_financial_limit: int = int(os.getenv("CANDIDATE_FINANCIAL_LIMIT", "30" if post_close_deep else "10"))

    data_dir: Path = PROJECT_ROOT / "assets" / "data"
    stock_data_dir: Path = PROJECT_ROOT / "assets" / "data" / "stocks"
    latest_file: Path = PROJECT_ROOT / "assets" / "data" / "latest.json"

    index_map_em: dict[str, str] = field(default_factory=lambda: {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000688": "科创50参考",
        "899050": "北证50",
    })

    index_map_sina: dict[str, tuple[str, str]] = field(default_factory=lambda: {
        "sh000001": ("000001", "上证指数"),
        "sz399001": ("399001", "深证成指"),
        "sz399006": ("399006", "创业板指"),
        "sh000688": ("000688", "科创50参考"),
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
