"""TickFlow SDK adapter used by the a-stock analysis pipeline."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import re
import time
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.pipeline.normalizer import detect_market, normalize_code

logger = logging.getLogger(__name__)


def to_tickflow_symbol(code: str) -> str:
    normalized = normalize_code(code)
    market = detect_market(normalized)
    if not market:
        raise ValueError(f"无法识别股票市场: {code}")
    return f"{normalized}.{market}"


def _code_from_tickflow_symbol(value: str) -> str:
    return normalize_code(value.split(".", 1)[0])


def _to_pandas(value: Any, *, symbol: str | None = None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for key, items in value.items():
            for item in items or []:
                row = dict(item or {})
                row.setdefault("symbol", key)
                rows.append(row)
        frame = pd.DataFrame(rows)
    elif isinstance(value, pd.DataFrame):
        frame = value.reset_index(drop=False)
    elif hasattr(value, "to_pandas"):
        frame = value.to_pandas()
    else:
        frame = pd.DataFrame(value)
    if symbol and "symbol" not in frame.columns:
        frame["symbol"] = symbol
    return frame


class TickFlowAPI:
    name = "tickflow"
    source_name = "tickflow"

    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()
        try:
            from tickflow import TickFlow
        except ImportError as exc:
            raise RuntimeError("缺少 TickFlow SDK，请运行 ./setup.sh") from exc
        # When an API key is present and paid history is enabled, use only the
        # paid client so daily-K batch consumes the purchased 200/request · 30/min
        # quota. Otherwise fall back to TickFlow.free() for offline/no-key runs.
        if self.config.tickflow_api_key:
            kwargs = {"api_key": self.config.tickflow_api_key}
            if self.config.tickflow_base_url:
                kwargs["base_url"] = self.config.tickflow_base_url
            self.client = TickFlow(**kwargs)
            use_paid_history = bool(getattr(self.config, "tickflow_use_paid_history", True))
            self.history_client = self.client if use_paid_history else TickFlow.free()
        else:
            self.client = TickFlow.free()
            self.history_client = self.client

    def fetch_daily_hist(self, symbol: str, adjust: str = "none") -> tuple[pd.DataFrame, str]:
        code = normalize_code(symbol)
        tf_symbol = to_tickflow_symbol(code)
        tickflow_adjust = {"qfq": "forward", "hfq": "backward", "none": "none"}.get(adjust, "none")
        # stock-sdk 作为个股历史主源：它通过 tickflow-stock-panel 的 Node
        # bridge 走批量/独立行情链路，避免逐股消耗 TickFlow 免费接口额度。
        if os.getenv("STOCK_SDK_PRIMARY", "1") == "1":
            try:
                from quant_system.data_source.stock_sdk_bridge import fetch_daily
                sdk_frame = fetch_daily(tf_symbol)
                if not sdk_frame.empty:
                    sdk_frame["symbol"] = tf_symbol
                    return sdk_frame.rename(columns={"trade_date": "date", "datetime": "date", "vol": "volume", "amt": "amount"}), "stock-sdk"
            except Exception as exc:
                logger.warning("stock-sdk 主源失败，回退 TickFlow(%s): %s", code, exc)
        # a-stock 的 worker 本来就是逐股调用；使用单标的接口可兼容没有 batch
        # 权限的 TickFlow 档位，避免有效 Key 因档位限制导致整只股票无法更新。
        raw = self.history_client.klines.get(
            tf_symbol, period="1d", adjust=tickflow_adjust,
            count=max(getattr(self.config, "research_hist_days", self.config.stock_hist_days), 250),
            as_dataframe=True,
        )
        frame = _to_pandas(raw, symbol=tf_symbol)
        if frame.empty and os.getenv("STOCK_SDK_FALLBACK", "1") == "1":
            from quant_system.data_source.stock_sdk_bridge import fetch_daily
            frame = fetch_daily(tf_symbol)
            if not frame.empty:
                frame["symbol"] = tf_symbol
                return frame.rename(columns={"trade_date": "date", "datetime": "date", "vol": "volume", "amt": "amount"}), "stock-sdk"
        frame = frame.rename(columns={"trade_date": "date", "datetime": "date", "vol": "volume", "amt": "amount"})
        return frame, self.source_name

    def fetch_daily_hist_batch(self, symbols: list[str], adjust: str = "none") -> dict[str, tuple[pd.DataFrame, str]]:
        """Fetch full-market bars in API batches, respecting plan request limits."""
        tickflow_symbols = [to_tickflow_symbol(symbol) for symbol in symbols]
        tickflow_adjust = {"qfq": "forward", "hfq": "backward", "none": "none"}.get(adjust, "none")
        size = max(1, min(int(self.config.tickflow_batch_size), 200))
        result: dict[str, tuple[pd.DataFrame, str]] = {}
        for start in range(0, len(tickflow_symbols), size):
            chunk = tickflow_symbols[start:start + size]
            for attempt in range(self.config.retry_times + 1):
                try:
                    frames = self.history_client.klines.batch(
                        chunk, period="1d", adjust=tickflow_adjust,
                        count=max(getattr(self.config, "research_hist_days", self.config.stock_hist_days), 250),
                        as_dataframe=True,
                        show_progress=False, max_workers=1, batch_size=size,
                    )
                    for tf_symbol, frame in (frames or {}).items():
                        normalized = _to_pandas(frame, symbol=tf_symbol).rename(
                            columns={"trade_date": "date", "datetime": "date", "vol": "volume", "amt": "amount"},
                        )
                        result[_code_from_tickflow_symbol(tf_symbol)] = (normalized, self.source_name)
                    break
                except Exception as exc:
                    if "权限" in str(exc):
                        raise RuntimeError(f"TickFlow 批量日 K 不可用: {exc}") from exc
                    if attempt >= self.config.retry_times:
                        logger.error("TickFlow 批量日 K 失败 %s..%s: %s", chunk[0], chunk[-1], exc)
                        break
                    match = re.search(r"请\s*(\d+)ms", str(exc))
                    wait_seconds = (int(match.group(1)) / 1000 + 0.5) if match else self.config.tickflow_batch_interval_sec
                    logger.warning("TickFlow 批量请求等待 %.1f 秒后重试", wait_seconds)
                    time.sleep(wait_seconds)
            if start + size < len(tickflow_symbols):
                time.sleep(max(0, self.config.tickflow_batch_interval_sec))
        return result

    def fetch_instruments(self) -> list[dict[str, str]]:
        rows: dict[str, dict[str, str]] = {}
        for exchange in ("SH", "SZ", "BJ"):
            for item in self.client.exchanges.get_instruments(exchange, instrument_type="stock") or []:
                if isinstance(item, dict):
                    raw = item
                elif hasattr(item, "model_dump"):
                    raw = item.model_dump()
                else:
                    raw = vars(item)
                symbol = str(raw.get("symbol") or raw.get("code") or "")
                code = _code_from_tickflow_symbol(symbol)
                if code.isdigit() and len(code) == 6:
                    ext = raw.get("ext") or {}
                    rows[code] = {
                        "code": code,
                        "name": str(raw.get("name") or code),
                        "symbol": symbol or to_tickflow_symbol(code),
                        "exchange": str(raw.get("exchange") or exchange),
                        "listing_date": str(ext.get("listing_date") or ""),
                        "total_shares": ext.get("total_shares"),
                        "float_shares": ext.get("float_shares"),
                        "tick_size": ext.get("tick_size"),
                        "limit_up": ext.get("limit_up"),
                        "limit_down": ext.get("limit_down"),
                        "is_st": "ST" in str(raw.get("name") or "").upper(),
                    }
        return sorted(rows.values(), key=lambda row: row["code"])

    def fetch_ex_factors(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        size = max(1, min(int(getattr(self.config, "tickflow_ex_factor_batch_size", 200)), 200))
        interval = float(getattr(self.config, "tickflow_ex_factor_interval_sec", 2.1))
        rows: list[dict[str, Any]] = []
        tickflow_symbols = [to_tickflow_symbol(symbol) for symbol in symbols]
        for start in range(0, len(tickflow_symbols), size):
            chunk = tickflow_symbols[start:start + size]
            raw = self.client.klines.ex_factors(chunk, as_dataframe=False, show_progress=False)
            frame = _to_pandas(raw)
            if not frame.empty:
                frame = frame.rename(columns={"timestamp": "trade_date", "date": "trade_date", "adj_factor": "ex_factor"})
                for item in frame.to_dict(orient="records"):
                    symbol = str(item.get("symbol") or "")
                    value = item.get("ex_factor")
                    trade_date = item.get("trade_date")
                    if symbol and value is not None and trade_date is not None:
                        rows.append({
                            "symbol": symbol,
                            "trade_date": str(trade_date)[:10],
                            "ex_factor": float(value),
                            "source": self.name,
                        })
            if start + size < len(tickflow_symbols):
                time.sleep(max(0.0, interval))
        return rows

    def fetch_spot_map(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes or not self.config.tickflow_api_key:
            return {}
        size = max(1, min(int(getattr(self.config, "tickflow_quote_batch_size", 50)), 50))
        interval = float(getattr(self.config, "tickflow_quote_interval_sec", 1.05))
        result: dict[str, dict[str, Any]] = {}
        for start in range(0, len(codes), size):
            chunk = codes[start:start + size]
            try:
                raw = self.client.quotes.get(symbols=[to_tickflow_symbol(code) for code in chunk])
            except Exception as exc:  # realtime is optional and tier-dependent
                logger.warning("TickFlow 实时行情不可用，继续使用日 K: %s", exc)
                return result
            frame = _to_pandas(raw)
            for row in frame.to_dict(orient="records"):
                code = _code_from_tickflow_symbol(str(row.get("symbol") or row.get("code") or ""))
                # SDK 的 DataFrame 模式会把扩展字段展开为 ext.* 列名。
                close = row.get("close") or row.get("last_price") or row.get("last") or row.get("price")
                if not code or close is None:
                    continue
                previous = row.get("pre_close") or row.get("prev_close") or row.get("previous_close")
                change = row.get("change") or row.get("ext.change_amount")
                ext_change_pct = row.get("ext.change_pct")
                change_pct = row.get("change_pct") or row.get("pct_chg")
                if change_pct is None and ext_change_pct is not None:
                    change_pct = float(ext_change_pct) * 100
                if change is None and previous:
                    change = float(close) - float(previous)
                if change_pct is None and previous:
                    change_pct = (float(close) / float(previous) - 1) * 100
                result[code] = {
                    "code": code, "name": row.get("name") or row.get("ext.name") or "", "close": float(close),
                    "change": float(change or 0), "change_pct": float(change_pct or 0),
                    "open": float(row.get("open") or close), "high": float(row.get("high") or close),
                    "low": float(row.get("low") or close), "volume": float(row.get("volume") or row.get("vol") or 0),
                    "amount_yi": float(row.get("amount") or row.get("amt") or 0) / 1e8,
                }
            if start + size < len(codes):
                time.sleep(max(0.0, interval))
        return result


def create_market_data_api(config: CrawlerConfig):
    if config.data_source == "tickflow":
        return TickFlowAPI(config)
    if config.data_source == "akshare":
        from quant_system.data_source.akshare_api import AkShareAPI
        return AkShareAPI(config)
    raise ValueError(f"不支持的数据源 STOCK_DATA_SOURCE={config.data_source!r}")
