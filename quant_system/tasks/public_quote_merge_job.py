"""Merge Tencent closing quotes into local qfq histories deterministically."""

from __future__ import annotations

import gzip
import json
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


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _merge_row(last: dict[str, Any], quote: dict[str, Any], trade_date: str, code: str) -> dict[str, Any] | None:
    previous_raw = float(quote.get("previous_close") or 0)
    previous_qfq = float(last.get("close") or 0)
    if previous_raw <= 0 or previous_qfq <= 0:
        return None
    factor = previous_qfq / previous_raw
    prices = {}
    for key, fallback in (("open", "price"), ("high", "price"), ("low", "price"), ("close", "price")):
        raw = float(quote.get(key if key != "close" else "price") or quote.get(fallback) or 0)
        if raw <= 0:
            return None
        prices[key] = round(raw * factor, 6)
    return {
        "symbol": quote.get("symbol"), "name": quote.get("name"), "date": trade_date,
        "trade_time": f"{trade_date} 15:00:00", **prices,
        "volume": float(quote.get("volume_lot") or 0),
        "amount": float(quote.get("amount_yi") or 0) * 1e8,
        "turnover": float(quote.get("turnover_pct") or 0),
        "code": code, "adj_type": "qfq",
        "merge_source": "tencent_close_scaled_by_previous_qfq",
        "qfq_scale": factor,
    }


def run_public_quote_merge(cfg: CrawlerConfig | None = None, target_trade_date: str | None = None) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    snapshot = _read(cfg.data_dir / "normalized/market.quotes.tencent/latest.json")
    trade_date = _date(snapshot.get("trade_date"))
    if not trade_date or (target_trade_date and trade_date < target_trade_date):
        return {
            "status": "unavailable", "updated_at": now_str(), "trade_date": trade_date or None,
            "target_trade_date": target_trade_date, "reason": "tencent_snapshot_stale_or_missing",
        }
    quotes = {
        str(row.get("code")): row for row in snapshot.get("items") or []
        if row.get("code") and is_research_stock_code(str(row.get("code")))
    }
    merged = already_current = failed = 0
    merged_codes: list[str] = []
    for code, quote in quotes.items():
        history_path = cfg.data_dir / "history" / f"{code}.json.gz"
        stock_path = cfg.data_dir / "stocks" / f"{code}.json"
        if not history_path.exists() or not stock_path.exists():
            failed += 1
            continue
        try:
            with gzip.open(history_path, "rt", encoding="utf-8") as stream:
                rows = json.load(stream)
            if not rows:
                failed += 1
                continue
            last_date = _date(rows[-1].get("date") or rows[-1].get("trade_date"))
            if last_date >= trade_date:
                already_current += 1
                continue
            row = _merge_row(rows[-1], quote, trade_date, code)
            if row is None:
                failed += 1
                continue
            rows.append(row)
            temporary_history = history_path.with_name(f".{history_path.name}.tmp")
            with gzip.open(temporary_history, "wt", encoding="utf-8", compresslevel=5) as stream:
                json.dump(rows, stream, ensure_ascii=False, separators=(",", ":"))
            temporary_history.replace(history_path)

            stock = _read(stock_path)
            stock["trade_date"] = trade_date
            stock["updated_at"] = now_str()
            stock["quote"] = {
                **(stock.get("quote") or {}),
                "close": quote.get("price"), "open": quote.get("open"),
                "high": quote.get("high"), "low": quote.get("low"),
                "change": quote.get("change"), "change_pct": quote.get("change_pct"),
                "volume": quote.get("volume_lot"), "amount_yi": quote.get("amount_yi"),
            }
            stock["kline"] = (stock.get("kline") or [])[-119:] + [row]
            stock["kline_source"] = "historical_qfq+tencent_close_scaled"
            temporary_stock = stock_path.with_suffix(".tmp")
            temporary_stock.write_text(json.dumps(stock, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary_stock.replace(stock_path)
            merged += 1
            merged_codes.append(code)
        except (OSError, ValueError, TypeError, KeyError):
            failed += 1

    status = "complete" if merged + already_current >= max(1, len(quotes) - failed) else "partial"
    payload = {
        "status": status, "updated_at": now_str(), "trade_date": trade_date,
        "target_trade_date": target_trade_date, "quote_count": len(quotes),
        "merged": merged, "already_current": already_current, "failed": failed,
        "method": "previous_qfq_close / tencent_previous_raw_close",
        "limitations": ["latest_bar_only", "requires_valid_previous_close", "not_used_before_provider_close_timestamp"],
        "merged_codes": merged_codes,
    }
    status_path = cfg.data_dir / "public_quote_merge/status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if merged:
        index_path = cfg.data_dir / "stocks/index.json"
        index = _read(index_path)
        index["updated_at"] = now_str()
        index["trade_date"] = trade_date
        index["refresh_source"] = "tencent_close_scaled"
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
