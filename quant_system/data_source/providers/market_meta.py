"""Market metadata provider mixin: indices, industries and fund flow."""

from __future__ import annotations

from typing import Any

from quant_system.utils.source_guard import is_eastmoney_disabled, is_ths_disabled, note_eastmoney_failure


class MarketMetaProviderMixin:
    def fetch_indices(self) -> list[dict[str, Any]]:
        if self.config.prefer_source != "sina" and not is_eastmoney_disabled():
            try:
                indices = self._em.fetch_indices()
                if indices:
                    return indices
            except Exception as e:
                note_eastmoney_failure(e)
                self.log_fail(f"东财指数不可用: {e}")

        index_df = self._retry(self.ak.stock_zh_index_spot_sina)
        indices = []
        for sina_code, (code, name) in self.config.index_map_sina.items():
            row = index_df[index_df["代码"] == sina_code]
            if row.empty:
                continue
            r = row.iloc[0]
            indices.append({
                "name": name, "code": code,
                "close": float(r["最新价"]),
                "change": float(r["涨跌额"]),
                "change_pct": float(r["涨跌幅"]),
            })
        self.log_ok(f"指数：新浪 {len(indices)} 个")
        return indices

    def fetch_industries(self) -> list[dict[str, Any]]:
        if self.config.prefer_source == "ths" and not is_ths_disabled():
            try:
                return self._ths.fetch_industries()
            except Exception as e:
                self.log_fail(f"同花顺行业不可用: {e}")

        if self.config.prefer_source != "sina" and not is_eastmoney_disabled():
            try:
                return self._em.fetch_industries()
            except Exception as e:
                note_eastmoney_failure(e)
                self.log_fail(f"东财行业不可用: {e}")

        if not is_ths_disabled():
            try:
                return self._ths.fetch_industries()
            except Exception as e:
                self.log_fail(f"同花顺行业不可用: {e}")

        industry_df = self._retry(lambda: self.ak.stock_fund_flow_industry(symbol="即时"))
        industries = [
            {"name": str(r["行业"]), "change_pct": float(r["行业-涨跌幅"])}
            for _, r in industry_df.head(self.config.industry_top_n).iterrows()
        ]
        self.log_ok(f"行业：同花顺 {len(industries)} 个")
        return industries

    def fetch_fund_flow(self) -> tuple[dict[str, float], str | None]:
        return self._em.fetch_fund_flow()
