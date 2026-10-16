"""市场范围过滤测试。"""

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import (
    filter_research_stocks,
    is_additional_permission_board_code,
    is_beijing_exchange_code,
    is_chinext_code,
    is_reference_only_stock,
    is_research_stock_code,
    is_star_board_code,
)


def test_star_board_code_detection():
    assert is_star_board_code("688001")
    assert is_star_board_code("sh689009")
    assert not is_star_board_code("600378")
    assert not is_star_board_code("300750")


def test_additional_permission_board_code_detection():
    assert is_chinext_code("sz300750")
    assert is_chinext_code("301001")
    assert is_beijing_exchange_code("920001")
    assert is_beijing_exchange_code("830001")
    assert is_beijing_exchange_code("430001")
    assert all(is_additional_permission_board_code(code) for code in ("688001", "300750", "920001"))
    assert not is_additional_permission_board_code("600519")
    assert not is_additional_permission_board_code("000001")


def test_star_board_reference_only_by_default():
    assert is_reference_only_stock("688001", CrawlerConfig())
    assert not is_reference_only_stock("600378", CrawlerConfig())


def test_filter_research_stocks_skips_every_additional_permission_board():
    rows = [
        {"code": "600378", "name": "昊华科技"},
        {"code": "688001", "name": "华兴源创"},
        {"code": "300750", "name": "宁德时代"},
        {"code": "920925", "name": "北交测试"},
        {"code": "200012", "name": "深市B股"},
        {"code": "900901", "name": "沪市B股"},
        {"code": "000988", "name": "华工科技"},
    ]

    kept = filter_research_stocks(rows, CrawlerConfig(), reason="测试")

    assert [x["code"] for x in kept] == ["600378", "000988"]


def test_research_stock_code_is_main_board_allowlist():
    assert all(is_research_stock_code(code) for code in ("000001", "001979", "002594", "003816", "600519", "601318", "603259", "605499"))
    assert not any(is_research_stock_code(code) for code in ("200012", "300750", "688001", "830001", "900901", "920001"))
