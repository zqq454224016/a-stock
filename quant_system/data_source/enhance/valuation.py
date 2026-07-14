"""Valuation enhance provider."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.data_source.enhance.runtime import latest_row, safe_float
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.source_guard import is_ths_disabled
from quant_system.utils.time_utils import today_str


class ValuationProviderMixin:
    def fetch_valuation(self, code: str) -> tuple[dict[str, Any], list[str]]:
        code = normalize_code(code)
        failed: list[str] = []
        out: dict[str, Any] = {"source": None}

        df, err = self._call("valuation_em", lambda: self.ak.stock_value_em(symbol=code))
        if err:
            failed.append(err)
        row = latest_row(df) if isinstance(df, pd.DataFrame) else None
        if row is not None:
            market_cap = safe_float(row.get("总市值"))
            float_cap = safe_float(row.get("流通市值"))
            out.update({
                "trade_date": str(row.get("数据日期", ""))[:10],
                "close": safe_float(row.get("当日收盘价")),
                "market_cap_yi": round(market_cap / 1e8, 2) if market_cap else None,
                "float_cap_yi": round(float_cap / 1e8, 2) if float_cap else None,
                "pe_ttm": safe_float(row.get("PE(TTM)")),
                "pe_static": safe_float(row.get("PE(静)")),
                "pb": safe_float(row.get("市净率")),
                "ps": safe_float(row.get("市销率")),
                "peg": safe_float(row.get("PEG值")),
                "source": "eastmoney_value",
            })
            return out, failed

        pe_df, err = self._call(
            "valuation_baidu_pe",
            lambda: self.ak.stock_zh_valuation_baidu(symbol=code, indicator="市盈率(TTM)"),
        )
        if err:
            failed.append(err)
        pe_row = latest_row(pe_df) if isinstance(pe_df, pd.DataFrame) else None
        if pe_row is not None:
            out["pe_ttm"] = safe_float(pe_row.get("value"))
            out["trade_date"] = str(pe_row.get("date", today_str()))[:10]
            out["source"] = "baidu_pe"

        pb_df, err = self._call(
            "valuation_baidu_pb",
            lambda: self.ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率"),
        )
        if err:
            failed.append(err)
        pb_row = latest_row(pb_df) if isinstance(pb_df, pd.DataFrame) else None
        if pb_row is not None:
            out["pb"] = safe_float(pb_row.get("value"))
            if not out.get("source"):
                out["source"] = "baidu_pb"
            if not out.get("trade_date"):
                out["trade_date"] = str(pb_row.get("date", today_str()))[:10]

        info_df, err = self._call("individual_info", lambda: self.ak.stock_individual_info_em(symbol=code))
        if err:
            failed.append(err)
        if isinstance(info_df, pd.DataFrame) and not info_df.empty:
            info = dict(zip(info_df["item"].astype(str), info_df["value"]))
            out.setdefault("market_cap_yi", safe_float(info.get("总市值")))
            out.setdefault("float_cap_yi", safe_float(info.get("流通市值")))
            out.setdefault("pe_ttm", safe_float(info.get("市盈率-动态") or info.get("市盈率")))
            out.setdefault("pb", safe_float(info.get("市净率")))
            if not out.get("source"):
                out["source"] = "eastmoney_info"

        if not out.get("source") and not is_ths_disabled():
            try:
                ths_val = self._ths.fetch_valuation(code)
                for k, v in ths_val.items():
                    if v is not None and out.get(k) is None:
                        out[k] = v
                if ths_val.get("source"):
                    out["source"] = ths_val["source"]
            except Exception:
                pass

        return out, failed
