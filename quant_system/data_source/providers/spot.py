"""Spot quote provider mixin."""

from __future__ import annotations

from typing import Any
import json

import pandas as pd

from quant_system.pipeline.normalizer import normalize_code
from quant_system.utils.logger import get_logger
from quant_system.utils.retry import call_with_retry
from quant_system.utils.source_guard import is_eastmoney_disabled, note_eastmoney_failure

logger = get_logger(__name__)


class SpotProviderMixin:
    def _spot_source_order(self) -> list[str]:
        prefer = self.config.prefer_source
        if prefer == "eastmoney":
            order = ["eastmoney", "sina", "tencent", "eastmoney_direct"]
        elif prefer == "sina":
            order = ["sina", "tencent", "eastmoney", "eastmoney_direct"]
        else:
            order = ["eastmoney", "sina", "tencent", "eastmoney_direct"]
        if is_eastmoney_disabled():
            order = [s for s in order if not s.startswith("eastmoney")]
        return order

    def _fetch_spot_source(self, source: str) -> pd.DataFrame:
        if source.startswith("eastmoney") and is_eastmoney_disabled():
            raise RuntimeError("eastmoney disabled")
        if source == "eastmoney":
            return call_with_retry(
                self._em.fetch_spot_all,
                retries=1,
                delay=self.config.retry_delay,
            )
        if source == "sina":
            return call_with_retry(
                self.ak.stock_zh_a_spot,
                retries=1,
                delay=self.config.retry_delay,
            )
        if source == "tencent":
            from quant_system.data_source.public_http import PublicHttpAPI
            index_path = self.config.data_dir / "stocks/index.json"
            payload = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            codes = [str(row.get("code") or "") for row in payload.get("stocks") or [] if row.get("code")]
            quotes = PublicHttpAPI(self.config).fetch_tencent_quotes(codes)
            return pd.DataFrame([{
                "代码": row["code"], "名称": row.get("name") or row["code"],
                "最新价": row.get("price"), "涨跌额": row.get("change") or 0,
                "涨跌幅": row.get("change_pct"), "昨收": row.get("previous_close") or 0,
                "今开": row.get("open") or 0, "最高": row.get("high") or 0,
                "最低": row.get("low") or 0, "成交量": float(row.get("volume_lot") or 0) * 100,
                "成交额": float(row.get("amount_yi") or 0) * 1e8,
                "时间戳": row.get("quote_time"),
            } for row in quotes])
        if source == "eastmoney_direct":
            return call_with_retry(
                self.ak.stock_zh_a_spot_em,
                retries=1,
                delay=self.config.retry_delay,
            )
        raise ValueError(f"未知行情源: {source}")

    def fetch_spot_all(self) -> pd.DataFrame:
        errors: list[str] = []
        for source in self._spot_source_order():
            try:
                df = self._fetch_spot_source(source)
                if df is not None and not df.empty:
                    label = {"eastmoney": "东财", "sina": "新浪", "tencent": "腾讯", "eastmoney_direct": "东财直连"}[source]
                    self.log_ok(f"个股快照：{label} {len(df)} 只")
                    return df
            except Exception as e:
                errors.append(f"{source}: {e}")
                self.log_fail(f"个股快照 {source} 失败: {e}")
                if source.startswith("eastmoney"):
                    note_eastmoney_failure(e)
        raise RuntimeError(f"全市场行情不可用: {'; '.join(errors)}")

    def _quotes_to_spot_df(self, spot_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for code, q in spot_map.items():
            if q.get("close") is None:
                continue
            rows.append({
                "代码": code,
                "名称": q.get("name") or code,
                "最新价": float(q["close"]),
                "涨跌额": float(q.get("change", 0) or 0),
                "涨跌幅": float(q.get("change_pct", 0) or 0),
                "今开": float(q.get("open", 0) or 0),
                "最高": float(q.get("high", 0) or 0),
                "最低": float(q.get("low", 0) or 0),
                "成交量": float(q.get("volume", 0) or 0),
                "成交额": float(q.get("amount_yi", 0) or 0) * 1e8,
            })
        return pd.DataFrame(rows)

    def _spot_df_from_stocks_cache(self, store: Any) -> pd.DataFrame:
        from collections import Counter

        payloads: list[tuple[str, dict[str, Any]]] = []
        stocks_dir = store.config.json_data_dir / "stocks"
        for path in stocks_dir.glob("[0-9]*.json"):
            code = normalize_code(path.stem)
            if not path.exists():
                continue
            data = store.read(path)
            payloads.append((code, data))

        # A cache directory can contain files refreshed on different days.  A
        # full-market ranking must be built from one coherent session, never by
        # mixing the newest handful of files with an older majority.
        date_counts = Counter(
            str(data.get("trade_date") or data.get("kline_date") or "")
            for _, data in payloads
            if data.get("trade_date") or data.get("kline_date")
        )
        cache_trade_date = max(
            date_counts,
            key=lambda value: (date_counts[value], value),
            default="",
        )
        spot_map: dict[str, dict[str, Any]] = {}
        for code, data in payloads:
            item_date = str(data.get("trade_date") or data.get("kline_date") or "")
            if not cache_trade_date or item_date != cache_trade_date:
                continue
            quote = data.get("quote") or {}
            if quote.get("close") is None:
                continue
            spot_map[code] = {**quote, "name": data.get("name", quote.get("name", ""))}
        frame = self._quotes_to_spot_df(spot_map)
        frame.attrs["trade_date"] = cache_trade_date
        frame.attrs["date_coverage"] = dict(sorted(date_counts.items(), reverse=True))
        return frame

    def _fetch_spot_map_per_code(self, codes: list[str]) -> dict[str, dict]:
        spot_map: dict[str, dict] = {}
        for code in sorted({normalize_code(c) for c in codes}):
            quote = self.fetch_spot_quote(code)
            if quote:
                spot_map[code] = quote
        return spot_map

    def _spot_row_to_quote(self, r: pd.Series) -> dict[str, Any]:
        amount = float(r.get("成交额", 0) or 0)
        return {
            "close": float(r["最新价"]),
            "change": float(r.get("涨跌额", 0) or 0),
            "change_pct": float(r["涨跌幅"]),
            "open": float(r.get("今开", 0) or 0),
            "high": float(r.get("最高", 0) or 0),
            "low": float(r.get("最低", 0) or 0),
            "volume": float(r.get("成交量", 0) or 0),
            "amount_yi": round(amount / 1e8, 2),
            "name": str(r["名称"]),
            "quote_source": "bulk_spot",
        }

    def fetch_spot_map(self, codes: list[str] | None = None) -> dict[str, dict]:
        """获取全市场快照；显式代码允许逐股降级，不存在隐式股票列表。"""
        codes_set = {normalize_code(c) for c in codes} if codes else None

        if codes_set and len(codes_set) <= 10:
            logger.info("指定股票 %s 只，拉取实时行情…", len(codes_set))
        else:
            logger.info("拉取全市场实时行情…")

        spot_map: dict[str, dict] = {}
        bulk_ok = False
        try:
            df = self.fetch_spot_all()
            bulk_ok = True
            for _, r in df.iterrows():
                code = normalize_code(str(r["代码"]))
                if codes_set is not None and code not in codes_set:
                    continue
                spot_map[code] = self._spot_row_to_quote(r)
        except Exception as e:
            logger.warning("全市场行情失败: %s", e)
            if codes_set is None:
                raise

        if codes_set:
            missing = codes_set - set(spot_map.keys())
            if missing:
                logger.warning("实时行情未找到 %s 只，尝试逐只拉取: %s", len(missing), ", ".join(sorted(missing)))
                for code in sorted(missing):
                    quote = self.fetch_spot_quote(code)
                    if quote:
                        spot_map[code] = quote
            still_missing = codes_set - set(spot_map.keys())
            if still_missing:
                logger.warning("实时行情仍缺失: %s", ", ".join(sorted(still_missing)))
            elif not bulk_ok:
                logger.info("指定股票行情已通过逐只降级获取 %s 只", len(spot_map))
        return spot_map
