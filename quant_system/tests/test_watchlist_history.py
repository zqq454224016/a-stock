"""watchlist 历史补录单元测试。"""

import json
from pathlib import Path

from quant_system.utils.watchlist_utils import insufficient_history_codes


def test_insufficient_history_codes(tmp_path, monkeypatch):
    data_dir = tmp_path / "assets" / "data";
    stocks_dir = data_dir / "stocks"
    stocks_dir.mkdir(parents=True)

    (stocks_dir / "600378.json").write_text(
        json.dumps({"kline": [{"date": "2026-01-01"}] * 100}),
        encoding="utf-8",
    )

    class _Cfg:
        mvp_hist_days = 750

    monkeypatch.setattr(
        "quant_system.utils.watchlist_utils.CrawlerConfig",
        lambda: _Cfg(),
    )
    monkeypatch.setattr(
        "quant_system.utils.watchlist_utils.get_watchlist_codes",
        lambda cfg=None: ["600378"],
    )

    class _Store:
        def __init__(self, config=None):
            self.config = type("C", (), {"json_data_dir": data_dir})()

        def read(self, path):
            return json.loads(path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "quant_system.utils.watchlist_utils.JsonStore",
        _Store,
    )

    assert "600378" in insufficient_history_codes(min_days=750)
