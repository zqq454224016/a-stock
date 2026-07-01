#!/usr/bin/env python3
"""采集大盘行情（兼容入口 → quant_system）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quant_system.tasks.daily_job import run_daily_market

if __name__ == "__main__":
    run_daily_market(mock="--mock" in sys.argv)
