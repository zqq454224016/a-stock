"""Fetch public-source supplements without making them implicit score inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.public_http import PublicHttpAPI
from quant_system.utils.logger import get_logger
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _universe_codes(cfg: CrawlerConfig) -> list[str]:
    master = _read(cfg.data_dir / "normalized/market.instruments/security_master.json")
    return [str(row.get("code")) for row in master.get("items") or [] if row.get("list_status") == "L" and row.get("code")]


def _candidate_codes(cfg: CrawlerConfig) -> list[str]:
    payload = _read(cfg.data_dir / "recommendations/summary.json")
    ranked: dict[str, float] = {}
    ai_evidence = _read(cfg.data_dir / "ai_long_term/evidence.json")
    # Long-horizon AI receives public data for its entire bounded scope. This
    # still does not make the data an automatic score input.
    for index, row in enumerate(ai_evidence.get("candidate_scope") or []):
        code = str(row.get("code") or "")
        if code:
            ranked[code] = max(ranked.get(code, 0.0), 10_000.0 - index)
    for period in (payload.get("periods") or {}).values():
        for row in period.get("recommendations") or []:
            code = str(row.get("code") or "")
            if code:
                ranked[code] = max(ranked.get(code, 0.0), float(row.get("score") or 0))
    return [
        code for code, _ in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))
        [:max(cfg.candidate_financial_limit, 12)]
    ]


def _quote_trade_date(rows: list[dict[str, Any]], fallback: str) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        compact = str(row.get("quote_time") or "")[:8]
        if len(compact) == 8 and compact.isdigit():
            day = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
            counts[day] = counts.get(day, 0) + 1
    return max(counts, key=counts.get) if counts else fallback


def run_public_supplement_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    if not cfg.public_supplement_enabled:
        return {"status": "disabled", "updated_at": now_str()}
    api = PublicHttpAPI(cfg)
    natural_date = date.today().isoformat()
    trade_date = natural_date
    result: dict[str, Any] = {"status": "available", "updated_at": now_str(), "datasets": {}, "errors": {}}

    try:
        quotes = api.fetch_tencent_quotes(_universe_codes(cfg))
        trade_date = _quote_trade_date(quotes, natural_date)
        payload = {
            "dataset": "market.quotes.tencent", "schema_version": "1.0.0", "trade_date": trade_date,
            "known_at": now_str(), "source": "tencent",
            "status": "available" if quotes else "empty",
            "count": len(quotes), "items": quotes,
            "usage": "freshness_and_cross_source_validation_only",
        }
        _write(cfg.data_dir / f"normalized/market.quotes.tencent/{trade_date}.json", payload)
        _write(cfg.data_dir / "normalized/market.quotes.tencent/latest.json", payload)
        result["datasets"]["tencent_quotes"] = {"status": "available" if quotes else "empty", "count": len(quotes)}
    except Exception as exc:
        result["errors"]["tencent_quotes"] = str(exc)

    pools: dict[str, list[dict[str, Any]]] = {}
    for pool in ("limit_up", "broken", "limit_down", "yesterday_limit_up"):
        try:
            pools[pool] = api.fetch_limit_pool(pool, trade_date)
        except Exception as exc:
            result["errors"][f"eastmoney_{pool}"] = str(exc)
            pools[pool] = []
    if any(pools.values()):
        up, broken, down, previous = (pools[name] for name in ("limit_up", "broken", "limit_down", "yesterday_limit_up"))
        denominator = len(up) + len(broken)
        summary = {
            "limit_up_count": len(up), "broken_count": len(broken), "limit_down_count": len(down),
            "yesterday_limit_up_count": len(previous),
            "broken_rate": round(len(broken) / denominator, 4) if denominator else None,
            "max_consecutive_limit_days": max((int(row.get("consecutive_limit_days") or 0) for row in up), default=0),
        }
        payload = {
            "dataset": "market.limit_pool.sentiment", "schema_version": "1.0.0",
            "trade_date": trade_date, "known_at": now_str(), "source": "eastmoney_push2ex",
            "status": "available",
            "summary": summary, "pools": pools, "usage": "deterministic_market_context_not_ai_score",
        }
        _write(cfg.data_dir / f"normalized/market.limit_pool.sentiment/{trade_date}.json", payload)
        _write(cfg.data_dir / "normalized/market.limit_pool.sentiment/latest.json", payload)
        result["datasets"]["limit_pool_sentiment"] = {"status": "available", **summary}

    candidates = _candidate_codes(cfg)
    financial_ok = 0
    candidate_market_ok = 0
    for code in candidates:
        try:
            statements = {
                kind: api.fetch_sina_financial_report(code, kind)
                for kind in ("fzb", "lrb", "llb")
            }
            payload = {
                "dataset": "financial.candidate_statements", "schema_version": "1.0.0",
                "code": code, "known_at": now_str(), "source": "sina",
                "statements": statements,
                "quality": {"complete_three_statements": all(statements.values())},
                "usage": "candidate_verification_only_not_automatic_score",
            }
            _write(cfg.data_dir / f"normalized/financial.candidate_statements/{code}.json", payload)
            financial_ok += int(payload["quality"]["complete_three_statements"])
        except Exception as exc:
            result["errors"][f"sina_financial_{code}"] = str(exc)
        candidate_data: dict[str, Any] = {}
        for name, fetch in (
            ("margin_trading", lambda: api.fetch_margin_trading(code)),
            ("block_trades", lambda: api.fetch_block_trades(code)),
            ("lockup_expiry", lambda: api.fetch_lockup_expiry(code, trade_date)),
        ):
            try:
                candidate_data[name] = fetch()
            except Exception as exc:
                result["errors"][f"eastmoney_{name}_{code}"] = str(exc)
                candidate_data[name] = [] if name != "lockup_expiry" else {"history": [], "upcoming": []}
        payload = {
            "dataset": "market.candidate_capital_events", "schema_version": "1.0.0",
            "code": code, "trade_date": trade_date, "known_at": now_str(),
            "sources": ["eastmoney_datacenter"], "data": candidate_data,
            "usage": "candidate_evidence_only_not_automatic_score",
        }
        _write(cfg.data_dir / f"normalized/market.candidate_capital_events/{code}.json", payload)
        candidate_market_ok += 1
    result["datasets"]["candidate_financials"] = {
        "status": "available" if financial_ok else "empty", "requested": len(candidates), "complete": financial_ok,
    }
    result["datasets"]["candidate_capital_events"] = {
        "status": "available" if candidate_market_ok else "empty",
        "requested": len(candidates), "written": candidate_market_ok,
    }

    official_lhb = api.fetch_official_dragon_tiger(trade_date)
    _write(cfg.data_dir / f"normalized/market.dragon_tiger.official/{trade_date}.json", {
        "dataset": "market.dragon_tiger.official", "schema_version": "1.0.0",
        "known_at": now_str(), "source": "sse+szse", **official_lhb,
        "usage": "official_evidence_and_fallback_not_automatic_score",
    })
    result["datasets"]["official_dragon_tiger"] = {
        "status": "partial" if official_lhb["errors"] else "available",
        "szse_count": len(official_lhb["szse"]),
        "sse_text_chars": len(official_lhb["sse_raw"]),
        "errors": official_lhb["errors"],
    }

    if result["errors"]:
        result["status"] = "partial" if result["datasets"] else "unavailable"
    _write(cfg.data_dir / "public_supplement/status.json", result)
    logger.info(
        "公开数据补充完成: 腾讯行情=%s 涨停=%s 炸板=%s 跌停=%s 候选三表=%s/%s 状态=%s",
        result["datasets"].get("tencent_quotes", {}).get("count", 0),
        len(pools.get("limit_up", [])), len(pools.get("broken", [])), len(pools.get("limit_down", [])),
        financial_ok, len(candidates), result["status"],
    )
    return result


if __name__ == "__main__":
    run_public_supplement_job()
