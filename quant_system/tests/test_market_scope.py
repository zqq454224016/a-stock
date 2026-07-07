"""市场范围过滤测试。"""

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import filter_research_stocks, is_reference_only_stock, is_star_board_code


def test_star_board_code_detection():
    assert is_star_board_code("688001")
    assert is_star_board_code("sh689009")
    assert not is_star_board_code("600378")
    assert not is_star_board_code("300750")


def test_star_board_reference_only_by_default():
    assert is_reference_only_stock("688001", CrawlerConfig())
    assert not is_reference_only_stock("600378", CrawlerConfig())


def test_filter_research_stocks_skips_star_board_reference():
    rows = [
        {"code": "600378", "name": "昊华科技"},
        {"code": "688001", "name": "华兴源创"},
        {"code": "000988", "name": "华工科技"},
    ]

    kept = filter_research_stocks(rows, CrawlerConfig(), reason="测试")

    assert [x["code"] for x in kept] == ["600378", "000988"]
