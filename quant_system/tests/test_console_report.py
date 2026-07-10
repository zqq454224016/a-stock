from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_console_module():
    path = Path(__file__).resolve().parents[2] / "script" / "gen_console_report.py"
    spec = importlib.util.spec_from_file_location("gen_console_report", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_console_payload_contains_stock_rows() -> None:
    mod = _load_console_module()
    payload = mod.build_console_payload()

    assert "summary" in payload
    assert "rows" in payload
    assert payload["summary"]["stock_count"] == len(payload["rows"])
    assert payload["module_links"]
    if payload["rows"]:
        row = payload["rows"][0]
        assert {"code", "name", "selector_status", "decision_action", "risk_level", "links"} <= set(row)


def test_console_render_embeds_filter_controls() -> None:
    mod = _load_console_module()
    html = mod.render({
        "summary": {"stock_count": 0, "candidate_count": 0, "buy_count": 0, "framework_signals": 0},
        "market": {"indices": [], "fund_flow": {}},
        "rows": [],
        "module_links": [],
    })

    assert "统一控制台" in html
    assert "console-search" in html
    assert "risk-filter" in html
    assert "console-data" in html
