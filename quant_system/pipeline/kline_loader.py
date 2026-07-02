"""K 线数据加载（统一 stocks / backfill / API 路径）。"""

from __future__ import annotations

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.data_source.akshare_api import AkShareAPI
from quant_system.pipeline.adjuster import apply_adjustment
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.normalizer import normalize_code, normalize_kline_df, to_symbol
from quant_system.storage.json_store import JsonStore
from quant_system.utils.time_utils import now_str


def make_data_version(code: str, df: pd.DataFrame) -> str:
    end = pd.to_datetime(df["date"].iloc[-1]).strftime("%Y%m%d")
    return f"daily_kline_{normalize_code(code)}_{end}"


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_kline_df(
    code: str,
    api: AkShareAPI,
    cfg: CrawlerConfig,
    store: JsonStore | None = None,
    *,
    prefer_api: bool = False,
    days: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    加载日 K DataFrame。
    返回 (df, meta)，meta 含 source / fetched_at / data_version。
    """
    code = normalize_code(code)
    store = store or JsonStore(DBConfig())
    meta: dict = {"code": code, "source": "api", "fetched_at": now_str()}

    if not prefer_api:
        stock_path = store.config.json_data_dir / "stocks" / f"{code}.json"
        if stock_path.exists():
            data = store.read(stock_path)
            rows = data.get("kline", [])
            if rows:
                meta.update({
                    "source": "stocks_json",
                    "fetched_at": data.get("updated_at", now_str()),
                    "quote_source": data.get("quote_source"),
                    "trade_date": data.get("trade_date"),
                })
                df = _rows_to_df(rows)
                meta["data_version"] = make_data_version(code, df)
                return df, meta

        backfill_path = store.config.json_data_dir / "backfill" / f"{code}.json"
        if backfill_path.exists():
            data = store.read(backfill_path)
            rows = data.get("klines", [])
            if rows:
                meta.update({"source": "backfill_json", "fetched_at": now_str()})
                df = _rows_to_df(rows)
                meta["data_version"] = make_data_version(code, df)
                return df, meta

    symbol = to_symbol(code)
    hist_days = days or cfg.stock_hist_days
    raw, daily_source = api.fetch_daily_hist(symbol, adjust="qfq")
    df = normalize_kline_df(raw, code, days=hist_days)
    df = clean_kline_df(df)
    df = apply_adjustment(df, adj_type="qfq")
    meta["daily_kline_source"] = daily_source
    meta["data_version"] = make_data_version(code, df)
    return df, meta


def load_stock_context(
    code: str,
    store: JsonStore | None = None,
) -> dict:
    """读取 stocks JSON 中的实时价上下文（若有）。"""
    store = store or JsonStore(DBConfig())
    code = normalize_code(code)
    path = store.config.json_data_dir / "stocks" / f"{code}.json"
    if not path.exists():
        return {}
    data = store.read(path)
    ctx: dict = {}
    if data.get("quote_source") == "spot" and data.get("quote"):
        ctx["close_override"] = float(data["quote"]["close"])
        ctx["trade_date"] = data.get("trade_date")
    return ctx
