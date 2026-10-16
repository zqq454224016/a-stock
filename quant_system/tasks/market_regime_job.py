"""Build a five-year point-in-time market-regime dataset from local daily bars."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from statistics import median
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.tasks.strategy_job import _write
from quant_system.utils.market_scope import is_additional_permission_board_code
from quant_system.utils.time_utils import now_str

MARKET_REGIME_VERSION = "2.0.0"


def run_market_regime_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    aggregate: dict[str, dict[str, float]] = defaultdict(lambda: {
        "stocks": 0, "advances": 0, "declines": 0, "return_sum": 0,
        "return_sq_sum": 0, "amount_sum": 0, "up_5": 0, "down_5": 0,
        "limit_up_proxy": 0, "limit_down_proxy": 0, "one_price_up": 0,
        "one_price_down": 0,
    })
    daily_returns: dict[str, list[float]] = defaultdict(list)
    history_root = cfg.data_dir / "history"
    used = 0
    for path in sorted(history_root.glob("*.json.gz")):
        if is_additional_permission_board_code(path.name.split(".", 1)[0]):
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                rows = json.load(stream)
            previous = None
            used += 1
            for row in rows[-cfg.research_hist_days:]:
                date = str(row.get("date") or row.get("trade_date") or "")[:10]
                close = float(row.get("close") or 0)
                if not date or close <= 0:
                    previous = close or previous
                    continue
                if previous and previous > 0:
                    change = close / previous - 1
                    item = aggregate[date]
                    item["stocks"] += 1
                    item["advances"] += int(change > 0)
                    item["declines"] += int(change < 0)
                    item["return_sum"] += change
                    item["return_sq_sum"] += change * change
                    item["amount_sum"] += float(row.get("amount") or 0)
                    item["up_5"] += int(change >= .05)
                    item["down_5"] += int(change <= -.05)
                    # Historical ST intervals are handled in execution_history.
                    # These two fields are explicitly proxies, never exact exchange pools.
                    item["limit_up_proxy"] += int(change >= .095)
                    item["limit_down_proxy"] += int(change <= -.095)
                    high = float(row.get("high") or close)
                    low = float(row.get("low") or close)
                    item["one_price_up"] += int(change >= .095 and abs(high - low) <= .005)
                    item["one_price_down"] += int(change <= -.095 and abs(high - low) <= .005)
                    daily_returns[date].append(change)
                previous = close
        except (OSError, ValueError, TypeError):
            continue

    rows_out: list[dict[str, Any]] = []
    for date, item in sorted(aggregate.items()):
        count = int(item["stocks"])
        if count < 100:
            continue
        mean = item["return_sum"] / count
        variance = max(0.0, item["return_sq_sum"] / count - mean * mean)
        rows_out.append({
            "date": date, "stocks": count, "advances": int(item["advances"]),
            "declines": int(item["declines"]), "advance_ratio": round(item["advances"] / count, 4),
            "mean_return_pct": round(mean * 100, 4),
            "median_return_pct": round(median(daily_returns[date]) * 100, 4),
            "cross_section_volatility_pct": round(variance ** .5 * 100, 4),
            "amount": round(item["amount_sum"], 2),
            "up_5_count": int(item["up_5"]), "down_5_count": int(item["down_5"]),
            "limit_up_proxy_count": int(item["limit_up_proxy"]),
            "limit_down_proxy_count": int(item["limit_down_proxy"]),
            "one_price_up_count": int(item["one_price_up"]),
            "one_price_down_count": int(item["one_price_down"]),
        })
    frame = pd.DataFrame(rows_out)
    if not frame.empty:
        frame["breadth_ma20"] = frame["advance_ratio"].rolling(20).mean()
        frame["return_ma20_pct"] = frame["mean_return_pct"].rolling(20).mean()
        frame["amount_ma20"] = frame["amount"].rolling(20).mean()
        frame["amount_ratio_20"] = frame["amount"] / frame["amount_ma20"]
        frame["limit_balance_proxy"] = (
            frame["limit_up_proxy_count"] - frame["limit_down_proxy_count"]
        ) / frame["stocks"]
        frame["sentiment_score"] = (
            50
            + (frame["advance_ratio"] - .5) * 60
            + frame["median_return_pct"].clip(-5, 5) * 4
            + frame["limit_balance_proxy"].clip(-.1, .1) * 100
        ).clip(0, 100)
        frame["sentiment_phase"] = "neutral"
        frame.loc[frame["sentiment_score"] <= 25, "sentiment_phase"] = "ice"
        frame.loc[(frame["sentiment_score"] > 25) & (frame["sentiment_score"] < 45), "sentiment_phase"] = "cool"
        frame.loc[(frame["sentiment_score"] >= 65) & (frame["sentiment_score"] < 80), "sentiment_phase"] = "hot"
        frame.loc[frame["sentiment_score"] >= 80, "sentiment_phase"] = "euphoria"
        frame["regime"] = "range"
        frame.loc[(frame["breadth_ma20"] >= .55) & (frame["return_ma20_pct"] > 0), "regime"] = "rising"
        frame.loc[(frame["breadth_ma20"] <= .45) & (frame["return_ma20_pct"] < 0), "regime"] = "falling"
        frame.loc[(frame["advance_ratio"] <= .20) & (frame["cross_section_volatility_pct"] >= 3), "regime"] = "extreme_risk"
        rows_out = json.loads(frame.where(pd.notna(frame), None).to_json(orient="records", force_ascii=False))
    latest_trade_date = str(rows_out[-1]["date"])[:10] if rows_out else None
    payload = {
        "status": "complete" if rows_out else "insufficient",
        "updated_at": now_str(), "version": MARKET_REGIME_VERSION,
        "source": "local_full_market_history",
        "stocks_used": used, "days": len(rows_out),
        "latest_trade_date": latest_trade_date,
        "items": rows_out,
        "limitations": [
            "涨跌停数量为按收益率计算的代理值，精确历史池仍需交易所/公开源逐日归档",
            "炸板历史无法由日线精确还原",
            "成交额字段覆盖取决于本地历史源",
        ],
        "field_semantics": {
            "limit_up_proxy_count": "非ST收益率>=9.5%的近似计数，不作为精确涨停池",
            "sentiment_score": "纯Python固定公式，仅用于市场状态分层",
        },
    }
    _write(cfg.data_dir / "market_regime/five_year.json", payload)
    _write(
        cfg.data_dir / "market_regime/status.json",
        {key: payload[key] for key in (
            "status", "updated_at", "source", "stocks_used", "days", "latest_trade_date", "limitations",
        )},
    )
    return payload


if __name__ == "__main__":
    run_market_regime_job()
