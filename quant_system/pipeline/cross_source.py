"""跨数据源日 K 一致性校验（东财 vs 新浪）。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.factor_config import CROSS_SOURCE_WARN_PCT
from quant_system.pipeline.cleaner import clean_kline_df
from quant_system.pipeline.normalizer import normalize_kline_df
from quant_system.utils.logger import get_logger

logger = get_logger(__name__)


def _close_series(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"]).dt.strftime("%Y-%m-%d")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    return work.dropna(subset=["close"]).drop_duplicates("date", keep="last")[["date", "close"]]


def compare_daily_close(
    primary_df: pd.DataFrame,
    alt_df: pd.DataFrame,
    *,
    lookback: int = 20,
    alt_source: str = "sina",
    warn_pct: float = 0.5,
) -> dict[str, Any]:
    """对比两源收盘价，返回 cross_source_diff（平均绝对偏差比例）及明细。"""
    if primary_df is None or primary_df.empty or alt_df is None or alt_df.empty:
        return {
            "cross_source_diff": None,
            "alt_source": alt_source,
            "compared_days": 0,
            "max_diff_pct": None,
            "warn_threshold_pct": warn_pct,
            "mismatch_days": [],
            "status": "skipped",
        }

    left = _close_series(primary_df).rename(columns={"close": "close_primary"})
    right = _close_series(alt_df).rename(columns={"close": "close_alt"})
    merged = left.merge(right, on="date", how="inner").tail(lookback)
    if merged.empty:
        return {
            "cross_source_diff": None,
            "alt_source": alt_source,
            "compared_days": 0,
            "max_diff_pct": None,
            "warn_threshold_pct": warn_pct,
            "mismatch_days": [],
            "status": "no_overlap",
        }

    base = merged["close_primary"].replace(0, float("nan"))
    diff_pct = ((merged["close_alt"] - merged["close_primary"]).abs() / base * 100).fillna(0)
    mean_diff = round(float(diff_pct.mean()) / 100, 6)
    max_diff = round(float(diff_pct.max()), 4)
    mismatch = merged.loc[diff_pct > warn_pct, "date"].tolist()

    status = "ok"
    if max_diff > warn_pct * 2:
        status = "error"
    elif max_diff > warn_pct or mismatch:
        status = "warning"

    return {
        "cross_source_diff": mean_diff,
        "alt_source": alt_source,
        "compared_days": len(merged),
        "max_diff_pct": max_diff,
        "warn_threshold_pct": warn_pct,
        "mismatch_days": mismatch,
        "status": status,
    }


def run_cross_source_check(
    api,
    cfg,
    symbol: str,
    code: str,
    primary_df: pd.DataFrame,
    daily_source: str,
) -> dict[str, Any]:
    """拉取备用源并与主源对比。"""
    if not getattr(cfg, "cross_source_check", True):
        return {"status": "disabled"}

    alt = "sina" if daily_source == "eastmoney" else "eastmoney"
    try:
        alt_raw = api.fetch_daily_hist_source(symbol, alt)
        alt_df = normalize_kline_df(alt_raw, code, days=cfg.stock_hist_days)
        alt_df = clean_kline_df(alt_df)
        return compare_daily_close(
            primary_df,
            alt_df,
            lookback=cfg.cross_source_lookback,
            alt_source=alt,
            warn_pct=CROSS_SOURCE_WARN_PCT,
        )
    except Exception as e:
        logger.warning("跨源校验 %s 跳过: %s", code, e)
        return {"status": "skipped", "alt_source": alt, "error": str(e)}
