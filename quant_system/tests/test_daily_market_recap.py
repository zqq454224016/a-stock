from __future__ import annotations

import json

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.daily_market_recap_job import run_daily_market_recap_job


def _write(root, rel, payload):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_daily_recap_attributes_market_to_sectors(tmp_path):
    cfg = CrawlerConfig()
    cfg.data_dir = tmp_path
    _write(tmp_path, "today_change/summary.json", {
        "trade_date": "2026-07-30", "market_state": "分化", "median_change_pct": 0.2,
        "breadth": {"advances": 1, "declines": 1, "advance_ratio": 0.5},
        "indices": [{"change_pct": -1}],
    })
    _write(tmp_path, "sector_data/stock_industry_map.json", {"stocks": {
        "600001": {"primary_industry": "银行"}, "600002": {"primary_industry": "电子"},
    }})
    _write(tmp_path, "stocks/600001.json", {
        "code": "600001", "trade_date": "2026-07-30", "quote": {"change_pct": 2, "amount_yi": 100},
    })
    _write(tmp_path, "stocks/600002.json", {
        "code": "600002", "trade_date": "2026-07-30", "quote": {"change_pct": -1, "amount_yi": 50},
    })
    _write(tmp_path, "normalized/market.limit_pool.sentiment/latest.json", {
        "summary": {"limit_up_count": 10, "broken_count": 2, "limit_down_count": 3, "broken_rate": 0.2},
    })

    result = run_daily_market_recap_job(cfg)

    assert result["status"] == "complete"
    assert result["sector_attribution"]["positive_contributors"][0]["name"] == "银行"
    assert result["sector_attribution"]["negative_contributors"][0]["name"] == "电子"
    assert result["sector_attribution"]["covered_stocks"] == 2
