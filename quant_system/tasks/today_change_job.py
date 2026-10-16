"""Build latest-session market and per-stock change analysis artifacts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from quant_system.analysis.today_change import analyze_stock_change, change_bucket, summarize_today
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.utils.market_scope import is_additional_permission_board_code
from quant_system.utils.time_utils import now_str
from quant_system.pipeline.normalizer import normalize_code


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_today_change_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    market = _read(cfg.data_dir / "latest.json")
    existing_summary = _read(cfg.data_dir / "today_change/summary.json")
    stock_payloads = [
        payload for path in sorted((cfg.data_dir / "stocks").glob("[0-9]*.json"))
        if (payload := _read(path)) and payload.get("trade_date")
    ]
    date_counts = Counter(str(payload.get("trade_date")) for payload in stock_payloads)
    # A few manually refreshed stocks must not redefine the full-market session.
    # Use the most widely covered date; ties prefer the latest date.
    trade_date = max(date_counts, key=lambda value: (date_counts[value], value), default="")
    latest_observed_trade_date = max(date_counts, default="")
    current = [payload for payload in stock_payloads if str(payload.get("trade_date")) == trade_date]
    index_changes = [
        float(item.get("change_pct") or 0)
        for item in (market.get("indices") or [])
        if not is_additional_permission_board_code(str(item.get("code") or ""))
    ]
    benchmark = sum(index_changes) / len(index_changes) if index_changes else 0.0
    output = cfg.data_dir / "today_change"
    rows: list[dict[str, Any]] = []
    used_live_snapshot = False
    # 收盘后的全市场快照可先用于当日广度与涨停初筛，不必等待逐股历史补录。
    # 量比等历史衍生字段保持缺失，后续日线合并后再补齐。
    market_trade_date = str(market.get("trade_date") or "")
    if market_trade_date and market_trade_date > trade_date:
        try:
            cached_spot = _read(cfg.data_dir / "market_spot/latest.json")
            live_items = cached_spot.get("items") or [] if str(cached_spot.get("trade_date") or "") == market_trade_date else []
            if not live_items:
                from quant_system.data_source.akshare_api import AkShareAPI
                live_items = AkShareAPI(CrawlerConfig()).fetch_spot_all().to_dict("records")
            for quote in live_items:
                code = normalize_code(str(quote.get("代码") or ""))
                name = str(quote.get("名称") or "")
                if is_additional_permission_board_code(code) or "ST" in name.upper():
                    continue
                previous = float(quote.get("昨收") or 0)
                open_price = float(quote.get("今开") or 0)
                close = float(quote.get("最新价") or 0)
                high = float(quote.get("最高") or 0)
                low = float(quote.get("最低") or 0)
                change_pct = float(quote.get("涨跌幅") or 0)
                row = {
                    "code": code, "name": name, "trade_date": market_trade_date,
                    "close": close, "change_pct": round(change_pct, 2),
                    "bucket": change_bucket(change_pct),
                    "gap_pct": round((open_price / previous - 1) * 100, 2) if previous and open_price else 0.0,
                    "intraday_pct": round((close / open_price - 1) * 100, 2) if open_price and close else 0.0,
                    "amplitude_pct": round((high - low) / previous * 100, 2) if previous and high >= low else 0.0,
                    "volume_ratio_5d": None, "amount": float(quote.get("成交额") or 0),
                    "benchmark_change_pct": round(benchmark, 2),
                    "relative_strength_pct": round(change_pct - benchmark, 2),
                    "drivers": ["全市场收盘快照"],
                    "limitations": ["尚未合并历史日线，量比不可用"],
                }
                _write(output / f"{code}.json", row)
                rows.append(row)
            used_live_snapshot = bool(rows)
            trade_date = market_trade_date
            latest_observed_trade_date = max(latest_observed_trade_date, market_trade_date)
            current = []
        except Exception as exc:
            # 刷新失败时保留上一份可验证结果，绝不以少量旧股票覆盖全市场摘要。
            return {**existing_summary, "refresh_status": "failed_preserved_previous", "refresh_error": str(exc), "requested_trade_date": market_trade_date}
    for stock in stock_payloads:
        if used_live_snapshot:
            break
        analysis = analyze_stock_change(stock, benchmark)
        _write(output / f"{stock['code']}.json", analysis)
        if str(stock.get("trade_date")) != trade_date:
            continue
        if not is_additional_permission_board_code(str(stock.get("code") or "")) and "ST" not in str(stock.get("name") or "").upper():
            rows.append(analysis)
    summary = summarize_today(
        rows,
        trade_date=trade_date,
        indices=list(market.get("indices") or []),
        industries=list(market.get("industries") or []),
    )
    summary.update({
        "updated_at": now_str(),
        "status": "complete" if len(rows) >= 1000 else "insufficient",
        "universe": "ordinary_a_share",
        "excluded_count": max(0, len(current) - len(rows)),
        "latest_observed_trade_date": latest_observed_trade_date,
        "date_coverage": dict(sorted(date_counts.items(), reverse=True)),
        "freshness_note": (
            f"已有少量股票更新至 {latest_observed_trade_date}，全市场分析仍采用覆盖最多的 {trade_date}"
            if latest_observed_trade_date > trade_date else "全市场分析日期与最新观测日期一致"
        ),
    })
    _write(output / "summary.json", summary)
    return summary
