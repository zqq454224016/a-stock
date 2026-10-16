from __future__ import annotations

import json
from types import SimpleNamespace

from quant_system.data_source import tushare_api


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_tushare_query_maps_fields(monkeypatch):
    payload = {"code": 0, "data": {"fields": ["ts_code", "adj_factor"], "items": [["600000.SH", 1.2]]}}
    monkeypatch.setattr(tushare_api, "urlopen", lambda request, timeout: Response(payload))
    api = tushare_api.TushareAPI(SimpleNamespace(tushare_token="token", request_timeout=3))

    assert api.query("adj_factor", trade_date="20260721") == [{"ts_code": "600000.SH", "adj_factor": 1.2}]


def test_tushare_api_requires_token():
    try:
        tushare_api.TushareAPI(SimpleNamespace(tushare_token=""))
    except RuntimeError as exc:
        assert "Token" in str(exc)
    else:
        raise AssertionError("missing token must fail explicitly")


def test_query_all_uses_offset(monkeypatch):
    api = tushare_api.TushareAPI(SimpleNamespace(tushare_token="token", request_timeout=3))
    offsets = []

    def query(api_name, **params):
        offsets.append(params["offset"])
        return [{"id": 1}, {"id": 2}] if params["offset"] == 0 else [{"id": 3}]

    monkeypatch.setattr(api, "query", query)
    assert len(api.query_all("stock_st", page_size=2)) == 3
    assert offsets == [0, 2]
