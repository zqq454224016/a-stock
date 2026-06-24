#!/usr/bin/env python3
"""爬取 A 股市场数据，输出 JSON 到 assets/data/。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
OUTPUT_FILE = DATA_DIR / "latest.json"


def fetch_with_akshare() -> dict:
    """使用 akshare 获取实时行情数据。"""
    import akshare as ak

    trade_date = datetime.now().strftime("%Y-%m-%d")
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 主要指数
    index_df = ak.stock_zh_index_spot_em()
    index_map = {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000688": "科创50",
        "899050": "北证50",
    }
    indices = []
    for code, name in index_map.items():
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

    # 全市场个股
    stock_df = ak.stock_zh_a_spot_em()
    stock_df = stock_df.dropna(subset=["涨跌幅"])

    def top_stocks(df, n=10, ascending=False):
        sorted_df = df.sort_values("涨跌幅", ascending=ascending).head(n)
        result = []
        for _, r in sorted_df.iterrows():
            result.append({
                "code": str(r["代码"]),
                "name": str(r["名称"]),
                "close": float(r["最新价"]),
                "change_pct": float(r["涨跌幅"]),
                "amount": round(float(r.get("成交额", 0)) / 1e8, 2),
            })
        return result

    # 涨跌分布
    pct = stock_df["涨跌幅"]
    distribution = [
        {"label": "涨停", "count": int((pct >= 9.9).sum()), "color": "#dc2626"},
        {"label": "涨幅>5%", "count": int(((pct >= 5) & (pct < 9.9)).sum()), "color": "#ef4444"},
        {"label": "涨幅0~5%", "count": int(((pct > 0) & (pct < 5)).sum()), "color": "#f87171"},
        {"label": "平盘", "count": int((pct == 0).sum()), "color": "#6b7280"},
        {"label": "跌幅0~5%", "count": int(((pct < 0) & (pct > -5)).sum()), "color": "#4ade80"},
        {"label": "跌幅>5%", "count": int(((pct <= -5) & (pct > -9.9)).sum()), "color": "#22c55e"},
        {"label": "跌停", "count": int((pct <= -9.9).sum()), "color": "#16a34a"},
    ]

    # 行业板块
    industries = []
    try:
        industry_df = ak.stock_board_industry_name_em()
        for _, r in industry_df.head(20).iterrows():
            industries.append({
                "name": str(r["板块名称"]),
                "change_pct": float(r["涨跌幅"]),
            })
    except Exception:
        pass

    # 北向资金
    fund_flow = {"north_net": 0, "main_net": 0, "retail_net": 0}
    try:
        north_df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        if not north_df.empty:
            fund_flow["north_net"] = round(float(north_df.iloc[-1]["value"]) / 1e8, 2)
    except Exception:
        pass

    return {
        "trade_date": trade_date,
        "updated_at": updated_at,
        "indices": indices,
        "market_distribution": distribution,
        "top_gainers": top_stocks(stock_df, ascending=False),
        "top_losers": top_stocks(stock_df, ascending=True),
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
    use_mock = "--mock" in sys.argv

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if use_mock:
        print("[fetch_data] 使用 mock 模式")
        data = fetch_mock()
    else:
        try:
            print("[fetch_data] 正在通过 akshare 拉取数据…")
            data = fetch_with_akshare()
        except ImportError:
            print("[fetch_data] akshare 未安装，回退到 mock 模式")
            data = fetch_mock()
        except Exception as e:
            print(f"[fetch_data] 拉取失败: {e}，回退到 mock 模式")
            data = fetch_mock()

    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[fetch_data] 已写入 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
