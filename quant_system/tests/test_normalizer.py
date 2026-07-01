"""normalizer 单元测试。"""

from quant_system.pipeline.normalizer import detect_market, normalize_code, to_symbol


def test_normalize_code():
    assert normalize_code("SH600519") == "600519"
    assert normalize_code("sz300308") == "300308"


def test_to_symbol():
    assert to_symbol("600519") == "sh600519"
    assert to_symbol("300308") == "sz300308"
    assert to_symbol("920249") == "bj920249"


def test_detect_market():
    assert detect_market("600519") == "SH"
    assert detect_market("000001") == "SZ"
    assert detect_market("920249") == "BJ"
