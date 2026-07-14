from __future__ import annotations

import importlib.util
from pathlib import Path

from quant_system.presentation.report_base import read_json, read_text, safe_json_script, write_html


def test_safe_json_script_escapes_closing_script() -> None:
    text = safe_json_script({"html": "</script><div>测试</div>"})

    assert "<\\/script>" in text
    assert "测试" in text


def test_write_and_read_json(tmp_path) -> None:
    path = tmp_path / "nested" / "report.html"
    write_html(path, "<html>ok</html>")

    assert path.read_text(encoding="utf-8") == "<html>ok</html>"
    assert read_json(tmp_path / "missing.json", {"fallback": True}) == {"fallback": True}
    assert read_text(tmp_path / "missing.html", "fallback") == "fallback"


def test_selector_report_uses_i18n_and_common_css() -> None:
    path = Path(__file__).resolve().parents[2] / "script" / "gen_selector_report.py"
    spec = importlib.util.spec_from_file_location("gen_selector_report_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    html = module.render([{"code": "000001", "status": "candidate", "upside_score": 80}])

    assert "候选" in html
    assert "../../css/common.css" in html


def test_stock_report_uses_common_css_and_safe_json() -> None:
    path = Path(__file__).resolve().parents[2] / "script" / "gen_stock_report.py"
    spec = importlib.util.spec_from_file_location("gen_stock_report_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data_files = sorted((Path(__file__).resolve().parents[2] / "assets" / "data" / "stocks").glob("*.json"))
    data = module.load_stock(next(p.stem for p in data_files if p.stem != "index"))
    html = module.render_stock_report(data)

    assert "../../css/common.css" in html
    assert "const stockData =" in html
    assert "<\\/script>" not in html


def test_market_report_uses_common_css_and_safe_json() -> None:
    path = Path(__file__).resolve().parents[2] / "script" / "gen_report.py"
    spec = importlib.util.spec_from_file_location("gen_report_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data = module.load_data()
    html = module.render_daily_report(data)

    assert "../../css/common.css" in html
    assert "const data =" in html
