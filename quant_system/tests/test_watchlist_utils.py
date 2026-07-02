"""watchlist 工具测试。"""

from quant_system.utils.watchlist_utils import get_watchlist_codes, missing_stock_data, resolve_codes


def test_resolve_codes_empty_uses_watchlist():
    codes = resolve_codes([])
    assert codes is None or isinstance(codes, list)


def test_resolve_codes_explicit():
    assert resolve_codes(["600378"]) == ["600378"]


def test_get_watchlist_codes():
    codes = get_watchlist_codes()
    assert isinstance(codes, list)


def test_missing_stock_data_subset():
    missing = missing_stock_data(["999999"])
    assert "999999" in missing
