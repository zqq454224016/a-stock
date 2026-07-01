"""兼容层：转发到 quant_system.pipeline.normalizer。"""

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code, to_symbol

ROOT = CrawlerConfig().data_dir.parent.parent  # a-stock
DATA_DIR = CrawlerConfig().data_dir
STOCK_DATA_DIR = CrawlerConfig().stock_data_dir
WATCHLIST_FILE = CrawlerConfig().watchlist_file

__all__ = [
    "ROOT", "DATA_DIR", "STOCK_DATA_DIR", "WATCHLIST_FILE",
    "normalize_code", "to_symbol", "load_watchlist",
]
