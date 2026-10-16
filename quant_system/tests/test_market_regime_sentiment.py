import gzip
import json
from types import SimpleNamespace

from quant_system.tasks.market_regime_job import run_market_regime_job


def test_market_regime_builds_deterministic_sentiment_fields(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    for index in range(120):
        code = f"600{index:03d}"
        rows = [
            {"date": "2026-07-23", "close": 10, "high": 10, "low": 10, "amount": 100},
            {
                "date": "2026-07-24", "close": 11 if index < 80 else 9.8,
                "high": 11 if index < 80 else 10, "low": 11 if index < 80 else 9.8,
                "amount": 120,
            },
        ]
        with gzip.open(root / f"{code}.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(rows, stream)
    payload = run_market_regime_job(SimpleNamespace(data_dir=tmp_path, research_hist_days=1250))
    row = payload["items"][0]
    assert row["stocks"] == 120
    assert row["limit_up_proxy_count"] == 80
    assert row["median_return_pct"] == 10
    assert row["sentiment_score"] > 50
    assert payload["latest_trade_date"] == "2026-07-24"
