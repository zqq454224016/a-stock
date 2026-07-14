"""Corporate action enhance provider."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.data_source.enhance.runtime import safe_float
from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.source_guard import is_ths_disabled
from quant_system.utils.time_utils import today_str


class CorporateProviderMixin:
    def fetch_dividends(self, code: str, limit: int = 5) -> tuple[list[dict[str, Any]], list[str]]:
        code = normalize_code(code)
        df, err = self._call(
            "dividend",
            lambda: self.ak.stock_history_dividend_detail(symbol=code, indicator="分红"),
        )
        if err or not isinstance(df, pd.DataFrame) or df.empty:
            return [], [err or "dividend"]
        rows: list[dict[str, Any]] = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "announce_date": str(r.get("公告日期", ""))[:10],
                "ex_date": str(r.get("除权除息日", ""))[:10],
                "record_date": str(r.get("股权登记日", ""))[:10],
                "cash_div": safe_float(r.get("派息")),
                "bonus_ratio": safe_float(r.get("送股")),
                "transfer_ratio": safe_float(r.get("转增")),
                "status": str(r.get("进度", "")),
            })
        return rows, []

    def fetch_lockup(self, code: str, limit: int = 3) -> tuple[list[dict[str, Any]], list[str]]:
        code = normalize_code(code)
        df, err = self._call(
            "lockup",
            lambda: self.ak.stock_restricted_release_queue_em(symbol=code),
        )
        if err or not isinstance(df, pd.DataFrame) or df.empty:
            return [], [err or "lockup"]
        rows: list[dict[str, Any]] = []
        for _, r in df.head(limit).iterrows():
            unlock_value = safe_float(r.get("实际解禁数量市值"))
            rows.append({
                "unlock_date": str(r.get("解禁时间", ""))[:10],
                "unlock_shares": safe_float(r.get("实际解禁数量")),
                "unlock_value_yi": round(unlock_value / 1e8, 2) if unlock_value else None,
                "pct_total": safe_float(r.get("占总市值比例")),
                "pct_float": safe_float(r.get("占流通市值比例")),
                "holder_type": str(r.get("限售股类型", "")),
            })
        return rows, []

    def fetch_earnings_forecast(self, code: str) -> tuple[dict[str, Any] | None, list[str]]:
        if self._is_disabled("earnings_forecast_probe"):
            return None, ["earnings_forecast"]
        code = normalize_code(code)
        year = int(today_str()[:4])
        dates = [f"{year}{md}" for md in ("1231", "0930", "0630", "0331")]
        failed: list[str] = []
        for d in dates:
            df, err = self._call(f"earnings_forecast_{d}", lambda date=d: self.ak.stock_yjyg_em(date=date))
            if err:
                failed.append(err)
                continue
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            sub = df[df["股票代码"].astype(str).map(normalize_code) == code]
            if sub.empty:
                continue
            r = sub.iloc[0]
            return {
                "indicator": str(r.get("预测指标", "")),
                "forecast_type": str(r.get("预告类型", "")),
                "change_pct": safe_float(r.get("业绩变动幅度")),
                "forecast_value": str(r.get("预测数值", "")),
                "reason": str(r.get("业绩变动原因", ""))[:200],
                "announce_date": str(r.get("公告日期", ""))[:10],
                "report_period": d,
            }, failed[:1]
        if failed:
            self._disable("earnings_forecast_probe")
        if not is_ths_disabled():
            try:
                ths_fc = self._ths.fetch_earnings_forecast(code)
                if ths_fc:
                    return ths_fc, failed[:1]
            except Exception:
                pass
        return None, failed[:1] if failed else ["earnings_forecast"]
