#!/usr/bin/env python3
"""采集自选股分析（兼容入口 → quant_system）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_system.pipeline.normalizer import normalize_code
from quant_system.tasks.stock_job import run_daily_stock

if __name__ == "__main__":
    codes = [normalize_code(a) for a in sys.argv[1:] if not a.startswith("-")]
    result = run_daily_stock(codes=codes or None)
    if not result and not codes:
        print("[fetch_stock] 请在 assets/data/watchlist.json 配置股票，或传入代码参数")
        print("  示例: python script/fetch_stock.py 600519 300308")
        sys.exit(1)
