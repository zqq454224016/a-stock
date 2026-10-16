"""Deterministic daily market recap with sector-level price/volume attribution."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def run_daily_market_recap_job(cfg: CrawlerConfig | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    today = _read(cfg.data_dir / "today_change/summary.json")
    mapping = (_read(cfg.data_dir / "sector_data/stock_industry_map.json").get("stocks") or {})
    sentiment = _read(cfg.data_dir / "normalized/market.limit_pool.sentiment/latest.json")
    trade_date = str(today.get("trade_date") or "")
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"stocks": 0, "advances": 0, "declines": 0, "change_sum": 0.0, "amount_yi": 0.0, "weighted_change": 0.0},
    )
    total_amount = 0.0
    covered = 0
    for path in sorted((cfg.data_dir / "stocks").glob("[0-9]*.json")):
        stock = _read(path)
        code = str(stock.get("code") or path.stem)
        if not is_research_stock_code(code) or str(stock.get("trade_date") or "") != trade_date:
            continue
        sector = mapping.get(code) or {}
        industry = str(sector.get("primary_industry") or "")
        if not industry:
            continue
        change = _number((stock.get("quote") or {}).get("change_pct"))
        amount = max(0.0, _number((stock.get("quote") or {}).get("amount_yi")))
        row = grouped[industry]
        row["stocks"] += 1
        row["advances"] += int(change > 0)
        row["declines"] += int(change < 0)
        row["change_sum"] += change
        row["amount_yi"] += amount
        row["weighted_change"] += change * amount
        total_amount += amount
        covered += 1

    sectors = []
    for industry, row in grouped.items():
        stocks = row["stocks"]
        amount = row["amount_yi"]
        average = row["change_sum"] / stocks if stocks else 0.0
        weighted = row["weighted_change"] / amount if amount else average
        sectors.append({
            "name": industry,
            "stock_count": stocks,
            "average_change_pct": round(average, 2),
            "amount_weighted_change_pct": round(weighted, 2),
            "advance_ratio": round(row["advances"] / max(1, row["advances"] + row["declines"]), 4),
            "amount_yi": round(amount, 2),
            "turnover_share": round(amount / total_amount, 4) if total_amount else None,
            "market_attribution_points": round((amount / total_amount) * weighted, 4) if total_amount else None,
        })
    sectors.sort(key=lambda row: row["market_attribution_points"] or 0, reverse=True)
    negative = sorted(sectors, key=lambda row: row["market_attribution_points"] or 0)
    breadth = today.get("breadth") or {}
    index_rows = today.get("indices") or []
    index_avg = sum(_number(row.get("change_pct")) for row in index_rows) / len(index_rows) if index_rows else 0.0
    limit_summary = sentiment.get("summary") or {}
    divergence = _number(breadth.get("advance_ratio")) >= 0.55 and index_avg < -0.5
    headline = (
        f"{trade_date} 市场{today.get('market_state') or '状态未知'}："
        f"上涨{breadth.get('advances', 0)}只、下跌{breadth.get('declines', 0)}只，"
        f"涨跌中位数{today.get('median_change_pct')}%。"
    )
    if divergence:
        headline += " 指数下跌但多数个股上涨，呈现明显指数—个股背离。"
    payload = {
        "dataset": "market.daily_recap",
        "schema_version": "1.0.0",
        "status": "complete" if sectors else "insufficient",
        "trade_date": trade_date,
        "updated_at": now_str(),
        "headline": headline,
        "market_structure": {
            "state": today.get("market_state"),
            "advance_ratio": breadth.get("advance_ratio"),
            "median_change_pct": today.get("median_change_pct"),
            "index_average_change_pct": round(index_avg, 2),
            "index_stock_divergence": divergence,
            "limit_up_count": limit_summary.get("limit_up_count"),
            "broken_count": limit_summary.get("broken_count"),
            "limit_down_count": limit_summary.get("limit_down_count"),
            "broken_rate": limit_summary.get("broken_rate"),
        },
        "sector_attribution": {
            "method": "industry_turnover_share_x_industry_amount_weighted_change",
            "covered_stocks": covered,
            "total_amount_yi": round(total_amount, 2),
            "positive_contributors": sectors[:8],
            "negative_contributors": negative[:8],
            "all": sectors,
        },
        "conclusions": [
            (
                f"主要正向板块：{('、'.join(row['name'] for row in sectors[:3])) or '暂无'}；"
                f"主要负向板块：{('、'.join(row['name'] for row in negative[:3])) or '暂无'}"
            ),
            (
                f"涨停{limit_summary.get('limit_up_count', 0)}家、炸板{limit_summary.get('broken_count', 0)}家、"
                f"跌停{limit_summary.get('limit_down_count', 0)}家，"
                f"炸板率{round(_number(limit_summary.get('broken_rate')) * 100, 1)}%"
            ),
        ],
        "limitations": [
            "板块归因是价格与成交额的算术分解，不证明政策、新闻或资金行为的真实因果",
            "同一公司按一级行业唯一归属，暂不重复计入概念板块",
            "盘中总结会随行情刷新，收盘后版本才可用于日度归档",
        ],
    }
    root = cfg.data_dir / "daily_market_recap"
    _write(root / f"{trade_date}.json", payload)
    _write(root / "latest.json", payload)
    return payload


if __name__ == "__main__":
    run_daily_market_recap_job()
