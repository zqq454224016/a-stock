"""数据清洗。"""

from __future__ import annotations

import pandas as pd


def clean_spot_df(df: pd.DataFrame) -> pd.DataFrame:
    """清洗全市场快照：去空值、转数值、过滤异常。"""
    df = df.copy()
    df = df.dropna(subset=["涨跌幅"])
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")
    df["成交额"] = pd.to_numeric(df.get("成交额", 0), errors="coerce").fillna(0)
    df = df.dropna(subset=["涨跌幅", "最新价"])
    df = df[df["最新价"] > 0]
    df = df[df["成交额"] >= 0]
    return df


def clean_kline_df(df: pd.DataFrame) -> pd.DataFrame:
    """清洗 K 线：剔除价格异常、零成交量停牌线。"""
    df = df.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["high"] >= df["low"]) & (df["open"] > 0) & (df["close"] > 0)]
    # 保留 volume=0 的停牌日，但剔除 high==low==0
    df = df[~((df["high"] == df["low"]) & (df["high"] == 0))]
    return df
