from __future__ import annotations

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks import runtime


def test_resolve_stock_items_prefers_explicit_codes() -> None:
    cfg = CrawlerConfig()

    items = runtime.resolve_stock_items(cfg, codes=["sh600378", "000636"], reason="测试")

    assert items == [{"code": "600378", "name": ""}, {"code": "000636", "name": ""}]


def test_run_for_watchlist_filters_failed_results(monkeypatch) -> None:
    cfg = CrawlerConfig()
    captured = {}
    saved = {}

    def fake_parallel_map(items, worker, max_workers, label):
        captured["max_workers"] = max_workers
        captured["label"] = label
        return [worker(item) for item in items]

    monkeypatch.setattr(runtime, "run_parallel_map", fake_parallel_map)

    rows = runtime.run_for_watchlist(
        cfg=cfg,
        items=[{"code": "1"}, {"code": "2"}],
        worker=lambda item: item if item["code"] == "1" else None,
        label="任务",
        on_success=lambda rows, ts: saved.update({"rows": rows, "ts": ts}),
    )

    assert rows == [{"code": "1"}]
    assert captured == {"max_workers": cfg.fetch_workers, "label": "任务"}
    assert saved["rows"] == [{"code": "1"}]
    assert saved["ts"]


def test_run_for_watchlist_empty_returns_empty() -> None:
    rows = runtime.run_for_watchlist(
        cfg=CrawlerConfig(),
        items=[],
        worker=lambda item: item,
        label="空任务",
    )

    assert rows == []
