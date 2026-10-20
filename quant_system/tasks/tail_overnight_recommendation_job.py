"""尾盘实时推荐：14:45 后用盘中行情合成当日K线，输出「尾盘进、次日出」名单并写前向影子账本。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.data_source.public_http import PublicHttpAPI
from quant_system.strategy.tail_overnight import SPECS, latest_signals
from quant_system.tasks.tail_overnight_iteration_job import _universe, load_history
from quant_system.utils.time_utils import now_str
from quant_system.utils.trade_calendar import get_calendar

PICKS_PER_SPEC = 5
MINUTE_CHECK_POOL = 10
TAIL_WINDOW = ("14:40", "14:57")
INDEX_CODES = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
STATUS_LABEL = {
    "formal": "正式推荐",
    "forward_passed_await_manual": "前向已过线，待人工确认",
    "research_candidate": "研究候选（回测过线，前向影子观察中）",
    "observation_only": "仅观察（回测未过线）",
}


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


def _elapsed_minutes(now: datetime) -> int:
    hm = now.hour * 60 + now.minute
    morning = max(0, min(hm, 11 * 60 + 30) - (9 * 60 + 30))
    afternoon = max(0, min(hm, 15 * 60) - 13 * 60)
    return max(1, min(240, morning + afternoon))


def _timing(now: datetime) -> str:
    clock = now.strftime("%H:%M")
    if clock >= "15:00":
        return "after_close"
    if clock >= TAIL_WINDOW[0]:
        return "tail_window" if clock <= TAIL_WINDOW[1] else "auction"
    return "too_early"


def _minute_checks(api: PublicHttpAPI, code: str, price: float, limit_up: float | None) -> dict[str, Any]:
    try:
        rows = [row for row in api.fetch_tencent_minutes(code) if row["close"] > 0]
    except Exception as exc:  # 分时缺失时失败关闭
        return {"passed": False, "reason": f"分时获取失败: {str(exc)[-60:]}"}
    if len(rows) < 120:
        return {"passed": False, "reason": "分时不足120根"}
    amount = sum(row["amount"] for row in rows)
    volume = sum(row["volume"] for row in rows)
    vwap = amount / (volume * 100) if volume else None
    tail = [row["close"] for row in rows if row["date"][11:16] >= "14:30"] or [rows[-1]["close"]]
    tail_high = max(tail)
    checks = {
        "above_vwap_now": vwap is None or price >= vwap,
        "no_tail_dump": price >= tail_high * 0.99,
        "not_limit_up_now": not (limit_up and price >= limit_up - 0.005),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "vwap": round(vwap, 3) if vwap else None,
        "tail_high": tail_high,
    }


def run_tail_overnight_recommendation(
    cfg: CrawlerConfig | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    cfg = cfg or CrawlerConfig()
    now = now or datetime.now()
    root = cfg.data_dir / "tail_overnight"
    calendar = get_calendar()
    trade_date = now.strftime("%Y-%m-%d")
    if not calendar.is_trade_day(trade_date):
        payload = {"status": "not_trade_day", "trade_date": trade_date, "updated_at": now_str()}
        _write(root / "recommendation.json", payload)
        return payload
    prev_day = calendar.prev_trade_day(trade_date)
    timing = _timing(now)
    scale = 240 / _elapsed_minutes(now)

    research = _read(root / "latest.json")
    spec_meta = research.get("specs") or {}
    api = PublicHttpAPI(cfg)
    universe = _universe(cfg)
    quotes = {row["code"]: row for row in api.fetch_tencent_quotes([code for code, _ in universe])}
    index_quotes = {row["code"]: row for row in api.fetch_tencent_quotes(list(INDEX_CODES))}

    stale: list[str] = []

    def evaluate(item: tuple[str, str]) -> list[dict[str, Any]]:
        code, name = item
        quote = quotes.get(code)
        if not quote or not quote.get("volume_lot"):
            return []
        frame = load_history(cfg, code)
        if frame is None or len(frame) < 80:
            return []
        frame = frame[frame["date"] < trade_date].tail(120)
        if frame.empty or frame["date"].iloc[-1] != prev_day:
            stale.append(code)
            return []
        today = {
            "date": trade_date,
            "open": quote.get("open"), "high": quote.get("high"), "low": quote.get("low"),
            "close": quote["price"],
            "volume": float(quote["volume_lot"]) * scale,
            "amount": float(quote.get("amount_yi") or 0) * 1e8 * scale,
        }
        merged = pd.concat([frame, pd.DataFrame([today])], ignore_index=True)
        hits = latest_signals(merged)
        for hit in hits:
            hit.update({
                "code": code, "name": name, "price": quote["price"],
                "change_pct": quote.get("change_pct"),
                "turnover_pct": quote.get("turnover_pct"),
                "float_cap_yi": quote.get("float_market_cap_yi"),
                "limit_up": quote.get("limit_up"),
            })
        return hits

    with ThreadPoolExecutor(max_workers=max(4, cfg.fetch_workers)) as pool:
        hits = [hit for chunk in pool.map(evaluate, universe) for hit in chunk]

    by_spec: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        by_spec.setdefault(hit["spec"], []).append(hit)
    checked: dict[str, dict[str, Any]] = {}
    pool_codes = {
        hit["code"]: hit
        for rows in by_spec.values()
        for hit in sorted(rows, key=lambda r: r["score"], reverse=True)[:MINUTE_CHECK_POOL]
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        for code, result in zip(
            pool_codes,
            pool.map(lambda c: _minute_checks(api, c, pool_codes[c]["price"], pool_codes[c]["limit_up"]), pool_codes),
        ):
            checked[code] = result

    specs_out: dict[str, Any] = {}
    ledger_picks: list[dict[str, Any]] = []
    for spec in SPECS:
        meta = spec_meta.get(spec.name) or {}
        status = meta.get("status") or "observation_only"
        ranked = sorted(by_spec.get(spec.name, []), key=lambda r: r["score"], reverse=True)
        picks = []
        for hit in ranked[:MINUTE_CHECK_POOL]:
            minute = checked.get(hit["code"]) or {"passed": False, "reason": "未做分时检查"}
            if not minute.get("passed"):
                continue
            picks.append({**hit, "minute": minute})
            if len(picks) >= PICKS_PER_SPEC:
                break
        holdout = meta.get("holdout") or {}
        specs_out[spec.name] = {
            "label": spec.label,
            "exit": spec.exit,
            "status": status,
            "status_label": STATUS_LABEL.get(status, status),
            "signal_count": len(ranked),
            "backtest_holdout": {
                "hit_rate": holdout.get("hit_rate"),
                "avg_net_return_pct": holdout.get("avg_net_return_pct"),
                "portfolio_total_return_pct": (holdout.get("portfolio") or {}).get("total_return_pct"),
            },
            "picks": picks,
        }
        for pick in picks:
            ledger_picks.append({
                "spec": spec.name, "code": pick["code"], "name": pick["name"],
                "exit": spec.exit, "decision_price": pick["price"], "score": pick["score"],
            })

    def collect(statuses: set[str]) -> list[dict[str, Any]]:
        rows = []
        for name, item in specs_out.items():
            if item["status"] in statuses:
                rows += [{**pick, "spec_label": item["label"], "status_label": item["status_label"]}
                         for pick in item["picks"]]
        return rows

    payload = {
        "status": "complete",
        "trade_date": trade_date,
        "updated_at": now_str(),
        "timing": timing,
        "plan": "T日收盘集合竞价买入（14:57-15:00），T+1 按策略在开盘或收盘卖出",
        "market": {
            "indices": {
                INDEX_CODES[key]: (index_quotes.get(key[2:]) or {}).get("change_pct") for key in INDEX_CODES
            },
            "prior_day": prev_day,
            "prior_day_regime": next(
                (row.get("regime") for row in (_read(cfg.data_dir / "market_regime/five_year.json").get("items") or [])
                 if row.get("date") == prev_day),
                None,
            ),
        },
        "research_available": bool(spec_meta),
        "stale_history_skipped": len(stale),
        "volume_scale": round(scale, 3),
        "formal": collect({"formal"}),
        "research_candidates": collect({"research_candidate", "forward_passed_await_manual"}),
        "observation": collect({"observation_only"}),
        "specs": specs_out,
        "limitations": [
            "盘中成交量按已开盘时长外推到全天，收盘竞价后会有偏差",
            "非正式推荐的名单只用于前向影子记账与观察，不是买入建议",
        ],
    }
    _write(root / "recommendation.json", payload)
    ledger_path = root / "shadow" / f"{trade_date}.json"
    if timing in {"tail_window", "auction"} and not ledger_path.exists():
        _write(ledger_path, {
            "trade_date": trade_date, "recorded_at": now_str(), "timing": timing,
            "research_version": research.get("research_version"), "picks": ledger_picks,
        })
        payload["shadow_recorded"] = True
    return payload


if __name__ == "__main__":
    result = run_tail_overnight_recommendation()
    brief = {
        "trade_date": result.get("trade_date"), "timing": result.get("timing"),
        "formal": [(r["code"], r["name"], r["spec"]) for r in result.get("formal") or []],
        "research_candidates": [(r["code"], r["name"], r["spec"]) for r in result.get("research_candidates") or []],
        "observation_count": len(result.get("observation") or []),
        "signals": {name: item["signal_count"] for name, item in (result.get("specs") or {}).items()},
    }
    print(json.dumps(brief, ensure_ascii=False, indent=1))
