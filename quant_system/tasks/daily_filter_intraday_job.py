"""Fetch and evaluate minute data for numerically eligible daily-filter candidates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.public_http import PublicHttpAPI
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


def evaluate_intraday(rows: list[dict[str, Any]]) -> dict[str, bool]:
    usable = sorted(
        (row for row in rows if row.get("date") and float(row.get("close") or 0) > 0),
        key=lambda row: str(row["date"]),
    )
    if len(usable) < 120:
        return {}
    cumulative_amount = cumulative_volume = 0.0
    above_vwap = True
    for row in usable:
        cumulative_amount += float(row.get("amount") or 0)
        cumulative_volume += float(row.get("volume") or 0)
        vwap = cumulative_amount / (cumulative_volume * 100) if cumulative_volume > 0 else 0
        if vwap > 0 and float(row["close"]) < vwap:
            above_vwap = False
    tail = [row for row in usable if str(row["date"])[11:16] >= "14:30"]
    if not tail:
        return {}
    tail_prices = [float(row["close"]) for row in tail]
    close = tail_prices[-1]
    tail_high = max(tail_prices)
    before_tail_high = max(float(row.get("high") or row["close"]) for row in usable if row not in tail)
    return {
        "above_vwap_all_day": above_vwap,
        "no_tail_pulse": tail_high <= 0 or (tail_high - close) / tail_high <= 0.005,
        "no_tail_drop": tail_prices[0] <= 0 or (close - tail_prices[0]) / tail_prices[0] >= -0.005,
        "late_high_pullback_holds": tail_high > before_tail_high and above_vwap,
    }


def _numerical_ready_codes(summary: dict[str, Any]) -> list[str]:
    """只给量价已过的票拉分时，避免「全市场缺分时」与「候选项为空」互相卡住。"""
    evaluated = ((summary.get("periods") or {}).get("short") or {}).get("evaluated") or []
    codes: list[str] = []
    for row in evaluated:
        daily = row.get("daily_filter") or {}
        if daily.get("numerical_passed"):
            codes.append(str(row.get("code") or ""))
            continue
        exclusion = daily.get("exclusion") or {}
        if exclusion.get("numerical_passed"):
            codes.append(str(row.get("code") or ""))
            continue
        blockers = list(daily.get("blockers") or [])
        non_intraday = [
            item for item in blockers
            if "分时" not in str(item) and "尾盘脉冲" not in str(item) and "尾盘无跳水" not in str(item)
        ]
        if blockers and not non_intraday:
            codes.append(str(row.get("code") or ""))
    return [code for code in dict.fromkeys(codes) if code]


def run_daily_filter_intraday_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    summary = _read(cfg.data_dir / "recommendations/summary.json")
    trade_date = str((summary.get("market_context") or {}).get("trade_date") or "")
    candidates = _numerical_ready_codes(summary)

    api = PublicHttpAPI(cfg)
    index_results = []
    errors: dict[str, str] = {}
    for code in ("sh000001", "sz399001"):
        try:
            index_results.append(evaluate_intraday(api.fetch_tencent_minutes(code)))
        except Exception as exc:
            errors[f"index_{code}"] = str(exc)[-200:]
    market_checks = {
        "market_above_vwap_all_day": bool(index_results) and all(
            result.get("above_vwap_all_day") is True for result in index_results
        ),
        "market_no_tail_drop": bool(index_results) and all(
            result.get("no_tail_drop") is True for result in index_results
        ),
    }
    stocks: dict[str, dict[str, bool]] = {}
    for code in candidates:
        try:
            result = evaluate_intraday(api.fetch_tencent_minutes(code))
            if not result:
                errors[code] = "minute_bars_insufficient"
                continue
            stocks[code] = {
                "stock_above_vwap_all_day": result.get("above_vwap_all_day") is True,
                "no_tail_pulse": result.get("no_tail_pulse") is True,
                "late_high_pullback_holds": result.get("late_high_pullback_holds") is True,
            }
        except Exception as exc:
            errors[code] = str(exc)[-200:]
    payload = {
        "status": "complete" if not errors else "partial",
        "trade_date": trade_date,
        "updated_at": now_str(),
        "candidate_count": len(candidates),
        "candidate_codes": candidates,
        "market_checks": market_checks,
        "stocks": stocks,
        "errors": errors,
        "selection_rule": "numerical_passed_only",
    }
    _write(cfg.data_dir / "daily_filter_intraday/latest.json", payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_daily_filter_intraday_job(), ensure_ascii=False))
