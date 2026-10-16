from quant_system.data_source.public_http import PublicHttpAPI, parse_tencent_quotes, tencent_prefix
from quant_system.tasks.public_supplement_job import _quote_trade_date


def test_tencent_prefix_routes_indices_etf_and_boards():
    assert tencent_prefix("600519") == "sh600519"
    assert tencent_prefix("510300") == "sh510300"
    assert tencent_prefix("000300") == "sh000300"
    assert tencent_prefix("000001") == "sz000001"
    assert tencent_prefix("920925") == "bj920925"


def test_parse_tencent_quotes():
    values = [""] * 88
    values[1:7] = ["贵州茅台", "600519", "1500.00", "1490.00", "1495.00", "1200"]
    values[30] = "20260726150000"
    values[31:35] = ["10", "0.67", "1510", "1480"]
    values[37:40] = ["123456", "0.8", "25"]
    values[43:49] = ["2.01", "18000", "22000", "8", "1639", "1341"]
    payload = 'v_sh600519="' + "~".join(values) + '";'
    row = parse_tencent_quotes(payload, {"sh600519": "600519"})[0]
    assert row["code"] == "600519"
    assert row["price"] == 1500
    assert row["pe_ttm"] == 25
    assert row["source"] == "tencent"


def test_normalize_limit_pool_row():
    row = PublicHttpAPI._normalize_limit_pool_row("limit_up", {
        "c": "600000", "n": "浦发银行", "p": 12340, "zdp": 10.01,
        "hs": 3.5, "amount": 1, "ltsz": 2, "fund": 3, "fbt": 93000,
        "lbt": 145900, "zbc": 1, "lbc": 2, "hybk": "银行",
        "zttj": {"days": 3, "ct": 2},
    })
    assert row["price"] == 12.34
    assert row["consecutive_limit_days"] == 2
    assert row["stat_limit_count"] == 2


def test_quote_trade_date_uses_observed_provider_timestamp():
    rows = [
        {"quote_time": "20260724150000"},
        {"quote_time": "20260724150001"},
        {"quote_time": "20260723150000"},
    ]
    assert _quote_trade_date(rows, "2026-07-26") == "2026-07-24"


def test_block_trade_normalizes_premium(monkeypatch):
    api = PublicHttpAPI()
    monkeypatch.setattr(api, "_eastmoney_datacenter", lambda *args, **kwargs: [{
        "TRADE_DATE": "2026-07-24 00:00:00", "DEAL_PRICE": 10.5,
        "CLOSE_PRICE": 10, "DEAL_VOLUME": 100, "DEAL_AMT": 1050,
        "BUYER_NAME": "买方", "SELLER_NAME": "卖方",
    }])
    row = api.fetch_block_trades("600000")[0]
    assert row["date"] == "2026-07-24"
    assert row["premium_pct"] == 5.0


def test_margin_trading_normalizes_fields(monkeypatch):
    api = PublicHttpAPI()
    monkeypatch.setattr(api, "_eastmoney_datacenter", lambda *args, **kwargs: [{
        "DATE": "2026-07-24", "RZYE": 100, "RZMRE": 20, "RZCHE": 10,
        "RQYE": 5, "RQMCL": 2, "RQCHL": 1, "RZRQYE": 105,
    }])
    row = api.fetch_margin_trading("600000")[0]
    assert row["financing_balance"] == 100
    assert row["margin_balance"] == 105
