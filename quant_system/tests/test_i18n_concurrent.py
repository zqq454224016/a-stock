"""i18n 与并发工具测试。"""

from unittest.mock import MagicMock, patch

from quant_system.utils.concurrent_fetch import run_parallel_map, run_parallel_tasks
from quant_system.utils.i18n_labels import (
    humanize_fetch_error,
    translate_limitations,
    translate_verdict,
)


def test_translate_limitations():
    assert "部分数据源失败" in translate_limitations(["partial_source_failure", "northbound_missing"])


def test_translate_verdict():
    assert translate_verdict("partial") == "部分一致"
    assert translate_verdict("aligned") == "一致"


def test_humanize_fetch_error():
    assert humanize_fetch_error(Exception("No tables found")) == "页面无数据"
    assert humanize_fetch_error(Exception("'NoneType' object is not subscriptable")) == "接口返回为空"


def test_run_parallel_map_order():
    out = run_parallel_map([1, 2, 3], lambda x: x * 10, max_workers=2, label="测试")
    assert out == [10, 20, 30]


def test_run_parallel_tasks():
    out = run_parallel_tasks({"a": lambda: 1, "b": lambda: 2}, max_workers=2)
    assert out["a"] == 1
    assert out["b"] == 2


def test_fetch_stock_bundle_parallel():
    from quant_system.data_source.enhance_api import EnhanceAPI

    api = EnhanceAPI()
    with patch.object(api, "fetch_valuation", return_value=({"pe_ttm": 10}, [])):
        with patch.object(api, "fetch_dividends", return_value=([], [])):
            with patch.object(api, "fetch_lockup", return_value=([], [])):
                with patch.object(api, "fetch_earnings_forecast", return_value=(None, [])):
                    with patch.object(api, "fetch_northbound", return_value=({}, [])):
                        with patch.object(api, "fetch_margin", return_value=(None, [])):
                            bundle = api.fetch_stock_bundle("600378")
    assert bundle["valuation"]["pe_ttm"] == 10
