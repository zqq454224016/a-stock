#!/usr/bin/env python3
"""爬取 A 股市场数据，输出 JSON 到 assets/data/。"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"

INDEX_MAP_EM = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000688": "科创50",
    "899050": "北证50",
}
INDEX_MAP_SINA = {
    "sh000001": ("000001", "上证指数"),
    "sz399001": ("399001", "深证成指"),
    "sz399006": ("399006", "创业板指"),
    "sh000688": ("000688", "科创50"),
    "bj899050": ("899050", "北证50"),
}


def _retry(fn, retries=3, delay=2):
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < retries - 1:
                print(f"  [retry {i + 1}/{retries - 1}] {e}")
                time.sleep(delay)
    raise last_err


def fetch_indices(ak) -> list[dict]:
    """主要指数：优先东财，失败切新浪。"""
    try:
        index_df = _retry(lambda: ak.stock_zh_index_spot_em())
        indices = []
        for code, name in INDEX_MAP_EM.items():
            row = index_df[index_df["代码"] == code]
            if row.empty:
                continue
            r = row.iloc[0]
            indices.append({
                "name": name,
                "code": code,
                "close": float(r["最新价"]),
                "change": float(r["涨跌额"]),
                "change_pct": float(r["涨跌幅"]),
            })
        if indices:
            print("[fetch_data] 指数数据：东财")
            return indices
    except Exception as e:
        print(f"[fetch_data] 东财指数不可用: {e}")

    index_df = _retry(lambda: ak.stock_zh_index_spot_sina())
    indices = []
    for sina_code, (code, name) in INDEX_MAP_SINA.items():
        row = index_df[index_df["代码"] == sina_code]
        if row.empty:
            continue
        r = row.iloc[0]
        indices.append({
            "name": name,
            "code": code,
            "close": float(r["最新价"]),
            "change": float(r["涨跌额"]),
            "change_pct": float(r["涨跌幅"]),
        })
    print("[fetch_data] 指数数据：新浪")
    return indices


def fetch_stocks(ak):
    """全 A 个股行情：优先东财，失败切新浪。"""
    import pandas as pd

    try:
        stock_df = _retry(lambda: ak.stock_zh_a_spot_em())
        source = "东财"
    except Exception as e:
        print(f"[fetch_data] 东财个股不可用: {e}")
        stock_df = _retry(lambda: ak.stock_zh_a_spot())
        source = "新浪"

    stock_df = stock_df.dropna(subset=["涨跌幅"])
    stock_df["涨跌幅"] = pd.to_numeric(stock_df["涨跌幅"], errors="coerce")
    stock_df["成交额"] = pd.to_numeric(stock_df.get("成交额", 0), errors="coerce").fillna(0)
    stock_df = stock_df.dropna(subset=["涨跌幅"])
    print(f"[fetch_data] 个股数据：{source}，共 {len(stock_df)} 只")
    return stock_df


def top_stocks(stock_df, n=10, ascending=False, sort_col="涨跌幅") -> list[dict]:
    sorted_df = stock_df.sort_values(sort_col, ascending=ascending).head(n)
    result = []
    for _, r in sorted_df.iterrows():
        amount = float(r.get("成交额", 0) or 0)
        result.append({
            "code": str(r["代码"]).replace("sh", "").replace("sz", "").replace("bj", ""),
            "name": str(r["名称"]),
            "close": float(r["最新价"]),
            "change_pct": float(r["涨跌幅"]),
            "amount": round(amount / 1e8, 2),
        })
    return result


def market_distribution(stock_df) -> list[dict]:
    pct = stock_df["涨跌幅"].astype(float)
    return [
        {"label": "涨停", "count": int((pct >= 9.9).sum()), "color": "#dc2626"},
        {"label": "涨幅>5%", "count": int(((pct >= 5) & (pct < 9.9)).sum()), "color": "#ef4444"},
        {"label": "涨幅0~5%", "count": int(((pct > 0) & (pct < 5)).sum()), "color": "#f87171"},
        {"label": "平盘", "count": int((pct == 0).sum()), "color": "#6b7280"},
        {"label": "跌幅0~5%", "count": int(((pct < 0) & (pct > -5)).sum()), "color": "#4ade80"},
        {"label": "跌幅>5%", "count": int(((pct <= -5) & (pct > -9.9)).sum()), "color": "#22c55e"},
        {"label": "跌停", "count": int((pct <= -9.9).sum()), "color": "#16a34a"},
    ]


def fetch_industries(ak) -> list[dict]:
    """行业板块涨跌幅。"""
    try:
        industry_df = _retry(lambda: ak.stock_board_industry_name_em())
        industries = [
            {"name": str(r["板块名称"]), "change_pct": float(r["涨跌幅"])}
            for _, r in industry_df.head(20).iterrows()
        ]
        print("[fetch_data] 行业数据：东财")
        return industries
    except Exception as e:
        print(f"[fetch_data] 东财行业不可用: {e}")

    industry_df = _retry(lambda: ak.stock_fund_flow_industry(symbol="即时"))
    industries = [
        {"name": str(r["行业"]), "change_pct": float(r["行业-涨跌幅"])}
        for _, r in industry_df.head(20).iterrows()
    ]
    print("[fetch_data] 行业数据：同花顺")
    return industries


def fetch_fund_flow(ak) -> dict:
    """北向 / 主力 / 行业净流入汇总。"""
    fund_flow = {"north_net": 0.0, "main_net": 0.0, "retail_net": 0.0}

    try:
        summary_df = _retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        north = summary_df[summary_df["资金方向"] == "北向"]
        if not north.empty:
            fund_flow["north_net"] = round(float(north["成交净买额"].sum()), 2)
        trade_date = str(summary_df.iloc[0]["交易日"])
        print(f"[fetch_data] 北向资金：{fund_flow['north_net']} 亿")
    except Exception as e:
        print(f"[fetch_data] 北向资金不可用: {e}")
        trade_date = None

    try:
        industry_df = _retry(lambda: ak.stock_fund_flow_industry(symbol="即时"))
        net_col = industry_df["净额"].astype(float)
        fund_flow["main_net"] = round(float(net_col.sum()), 2)
        print(f"[fetch_data] 行业净流入合计：{fund_flow['main_net']} 亿")
    except Exception as e:
        print(f"[fetch_data] 主力资金不可用: {e}")

    return fund_flow, trade_date


def fetch_with_akshare() -> dict:
    """使用 akshare 获取实时行情数据（多数据源自动降级）。"""
    import akshare as ak

    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trade_date = datetime.now().strftime("%Y-%m-%d")

    indices = fetch_indices(ak)
    stock_df = fetch_stocks(ak)
    industries = fetch_industries(ak)
    fund_flow, hsgt_date = fetch_fund_flow(ak)

    if hsgt_date:
        trade_date = hsgt_date

    return {
        "trade_date": trade_date,
        "updated_at": updated_at,
        "indices": indices,
        "market_distribution": market_distribution(stock_df),
        "top_gainers": top_stocks(stock_df, ascending=False),
        "top_losers": top_stocks(stock_df, ascending=True),
        "top_volume": top_stocks(stock_df, ascending=False, sort_col="成交额"),
        "industries": industries,
        "fund_flow": fund_flow,
    }


def fetch_mock() -> dict:
    """离线/演示模式：读取已有 sample 数据并更新时间戳。"""
    sample = DATA_DIR / "latest.json"
    if sample.exists():
        data = json.loads(sample.read_text(encoding="utf-8"))
    else:
        data = {
            "trade_date": datetime.now().strftime("%Y-%m-%d"),
            "indices": [],
            "market_distribution": [],
            "top_gainers": [],
            "top_losers": [],
            "industries": [],
            "fund_flow": {},
        }
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return data


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if "--mock" in sys.argv:
        print("[fetch_data] 使用 mock 模式")
        data = fetch_mock()
    else:
        print("[fetch_data] 正在拉取真实行情…")
        try:
            data = fetch_with_akshare()
            print(f"[fetch_data] 采集完成：{data['trade_date']}，指数 {len(data['indices'])} 个，"
                  f"涨幅榜 {data['top_gainers'][0]['name'] if data['top_gainers'] else '-'}")
        except ImportError:
            print("[fetch_data] akshare 未安装，回退到 mock 模式")
            data = fetch_mock()
        except Exception as e:
            print(f"[fetch_data] 拉取失败: {e}")
            sys.exit(1)

    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[fetch_data] 已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
