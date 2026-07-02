"""技术因子计算。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_system.config.factor_config import TECHNICAL_FACTOR_VERSION
from quant_system.pipeline.adjuster import calc_ma
from quant_system.utils.time_utils import now_str


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    if pd.isna(val) and float(gain.iloc[-1] or 0) > 0 and float(loss.iloc[-1] or 0) == 0:
        return 100.0
    return round(float(val), 2) if pd.notna(val) else None


def _macd(closes: pd.Series) -> tuple[float | None, float | None, float | None]:
    if len(closes) < 26:
        return None, None, None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    hist = macd_line - signal
    m, s, h = macd_line.iloc[-1], signal.iloc[-1], hist.iloc[-1]
    if pd.isna(m):
        return None, None, None
    return round(float(m), 4), round(float(s), 4), round(float(h), 4)


def _atr(df: pd.DataFrame, period: int = 14) -> float | None:
    if len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return round(float(atr), 4) if pd.notna(atr) else None


def _ma_cross(df: pd.DataFrame) -> str:
    if len(df) < 21 or "ma5" not in df.columns or "ma20" not in df.columns:
        return "none"
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    if prev["ma5"] <= prev["ma20"] and curr["ma5"] > curr["ma20"]:
        return "golden"
    if prev["ma5"] >= prev["ma20"] and curr["ma5"] < curr["ma20"]:
        return "death"
    return "none"


def compute_technical_factors(
    df: pd.DataFrame,
    code: str,
    trade_date: str | None = None,
    close_override: float | None = None,
    data_version: str | None = None,
) -> dict[str, Any]:
    """
    基于日 K 计算技术因子，输出 Quantification.md 标准结构。
    close_override: 用实时价覆盖末根收盘价（盘中场景）。
    """
    work = calc_ma(df.copy())
    if close_override is not None:
        work = work.copy()
        work.iloc[-1, work.columns.get_loc("close")] = close_override

    latest = work.iloc[-1]
    close = float(latest["close"])
    ma20 = float(latest["ma20"]) if pd.notna(latest.get("ma20")) else None
    ma20_bias = round((close / ma20 - 1) * 100, 2) if ma20 else None

    closes = work["close"].astype(float)
    volumes = work["volume"].astype(float) if "volume" in work.columns else pd.Series([0.0] * len(work))

    rsi14 = _rsi(closes, 14)
    macd, macd_signal, macd_hist = _macd(closes)
    atr14 = _atr(work, 14)

    momentum_20 = None
    if len(closes) > 20:
        base = float(closes.iloc[-21])
        momentum_20 = round((close / base - 1) * 100, 2) if base else None

    avg_vol = float(volumes.tail(20).mean()) if len(volumes) >= 5 else float(volumes.mean() or 1)
    cur_vol = float(volumes.iloc[-1])
    volume_ratio_20 = round(cur_vol / avg_vol, 2) if avg_vol > 0 else None

    td = trade_date or latest["date"].strftime("%Y-%m-%d")

    factors = {
        "ma20_bias": ma20_bias,
        "rsi14": rsi14,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "atr14": atr14,
        "momentum_20": momentum_20,
        "volume_ratio_20": volume_ratio_20,
        "above_ma20": bool(ma20 and close >= ma20),
        "ma_cross": _ma_cross(work),
    }

    return {
        "code": code,
        "trade_date": td,
        "factor_version": TECHNICAL_FACTOR_VERSION,
        "data_version": data_version,
        "factors": factors,
        "updated_at": now_str(),
    }
