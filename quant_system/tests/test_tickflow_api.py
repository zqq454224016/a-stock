from types import SimpleNamespace

import pandas as pd

from quant_system.data_source.tickflow_api import TickFlowAPI, to_tickflow_symbol
from quant_system.tasks import stock_job


def test_to_tickflow_symbol():
    assert to_tickflow_symbol("600519") == "600519.SH"
    assert to_tickflow_symbol("sz000001") == "000001.SZ"
    assert to_tickflow_symbol("830001") == "830001.BJ"


def test_tickflow_daily_adapter(monkeypatch):
    calls = {}
    monkeypatch.setenv("STOCK_SDK_PRIMARY", "0")
    monkeypatch.setenv("STOCK_SDK_FALLBACK", "0")

    class Klines:
        def get(self, symbol, **kwargs):
            calls["symbol"] = symbol
            calls["kwargs"] = kwargs
            return [{"trade_date": "2026-07-17", "open": 10, "high": 11, "low": 9, "close": 10.5, "vol": 100}]

    api = object.__new__(TickFlowAPI)
    api.config = SimpleNamespace(stock_hist_days=120, research_hist_days=120, tickflow_api_key="")
    api.client = SimpleNamespace(klines=Klines())
    api.history_client = api.client
    frame, source = api.fetch_daily_hist("sh600519", adjust="qfq")
    assert calls["symbol"] == "600519.SH"
    assert calls["kwargs"]["adjust"] == "forward"
    assert source == "tickflow"
    assert frame.iloc[0]["date"] == "2026-07-17"
    assert frame.iloc[0]["volume"] == 100


def test_tickflow_instruments_cover_exchanges():
    class Exchanges:
        def get_instruments(self, exchange, instrument_type=None):
            assert instrument_type == "stock"
            code = {"SH": "600000", "SZ": "000001", "BJ": "920001"}[exchange]
            return [{"symbol": f"{code}.{exchange}", "name": f"{exchange}测试", "exchange": exchange}]

    api = object.__new__(TickFlowAPI)
    api.client = SimpleNamespace(exchanges=Exchanges())
    rows = api.fetch_instruments()
    assert {row["exchange"] for row in rows} == {"SH", "SZ", "BJ"}


def test_tickflow_daily_batch_chunks_and_maps_codes(monkeypatch):
    calls = []

    class Klines:
        def batch(self, symbols, **kwargs):
            calls.append(symbols)
            return {symbol: pd.DataFrame([{
                "trade_date": "2026-07-21", "open": 10, "high": 11,
                "low": 9, "close": 10.5, "volume": 100,
            }]) for symbol in symbols}

    api = object.__new__(TickFlowAPI)
    api.config = SimpleNamespace(
        stock_hist_days=120, research_hist_days=120,
        tickflow_batch_size=2, tickflow_batch_interval_sec=0,
        retry_times=0,
    )
    api.client = SimpleNamespace(klines=Klines())
    api.history_client = api.client
    monkeypatch.setattr("quant_system.data_source.tickflow_api.time.sleep", lambda seconds: None)

    rows = api.fetch_daily_hist_batch(["600000", "000001", "920001"], adjust="qfq")

    assert calls == [["600000.SH", "000001.SZ"], ["920001.BJ"]]
    assert set(rows) == {"600000", "000001", "920001"}
    assert rows["600000"][1] == "tickflow"


def test_tickflow_daily_batch_permission_fails_without_retry(monkeypatch):
    class Klines:
        def batch(self, symbols, **kwargs):
            raise PermissionError("无批量查询权限")

    api = object.__new__(TickFlowAPI)
    api.config = SimpleNamespace(
        stock_hist_days=120, tickflow_batch_size=100, tickflow_batch_interval_sec=0,
        retry_times=3,
    )
    api.client = SimpleNamespace(klines=Klines())
    api.history_client = api.client
    sleeps = []
    monkeypatch.setattr("quant_system.data_source.tickflow_api.time.sleep", sleeps.append)

    try:
        api.fetch_daily_hist_batch(["600000"], adjust="qfq")
    except RuntimeError as exc:
        assert "批量日 K 不可用" in str(exc)
    else:
        raise AssertionError("permission failure must stop the full-market pipeline")
    assert sleeps == []


def test_batch_history_does_not_request_realtime_quotes(monkeypatch):
    class API:
        source_name = "tickflow"

        def fetch_spot_map(self, *, codes):
            raise AssertionError(f"batch history must not request realtime quotes: {codes}")

        def fetch_daily_hist_batch(self, symbols, adjust="none"):
            assert symbols == ["600000"]
            assert adjust == "qfq"
            return {}

    monkeypatch.setattr(stock_job, "create_market_data_api", lambda cfg: API())
    monkeypatch.setattr(stock_job, "JsonStore", lambda cfg: SimpleNamespace())
    monkeypatch.setattr(stock_job, "get_calendar", lambda: SimpleNamespace())
    monkeypatch.setattr(stock_job, "run_for_items", lambda **kwargs: [])

    assert stock_job.run_daily_stock(
        items=[{"code": "600000", "name": "浦发银行"}],
        batch_history=True,
    ) == []
