"""Hard-calculated short-term operating ranges for validated recommendations."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.iteration.trading_readiness import FINAL_SYSTEM_OBJECTIVE
from quant_system.utils.time_utils import now_str

INSTRUCTION_CONTRACT_VERSION = "1.0.0"


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _round_price(value: float) -> float:
    return round(max(0.01, value), 2)


def _history(cfg: CrawlerConfig, code: str) -> pd.DataFrame:
    with gzip.open(cfg.data_dir / "history" / f"{code}.json.gz", "rt", encoding="utf-8") as stream:
        frame = pd.DataFrame(json.load(stream))
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("date").dropna(subset=["high", "low", "close"]).reset_index(drop=True)


def _plan(code: str, name: str, score: float, replay: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    close = float(frame["close"].iloc[-1])
    previous_close = frame["close"].shift()
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous_close).abs(),
        (frame["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = float(true_range.tail(14).mean())
    ma5 = float(frame["close"].tail(5).mean())
    ma10 = float(frame["close"].tail(10).mean())
    high20 = float(frame["high"].tail(20).max())
    recent_support = float(frame["low"].tail(5).min())

    buy_low = max(ma5, close - atr14 * 0.80)
    buy_high = close - atr14 * 0.30
    # Short-term invalidation must stay close enough to cap risk; a distant
    # five-day swing low is reference support, not permission for a large loss.
    stop = max(recent_support - atr14 * 0.25, buy_low - atr14 * 0.35)
    target1 = max(high20, close + atr14 * 0.75)
    target2 = close + atr14 * 1.75
    breakout = high20 + 0.01
    max_chase = breakout + atr14 * 0.20
    risk_pct = (buy_high - stop) / buy_high * 100 if buy_high else 0
    risk_amount = max(0.0, buy_high - stop)
    reward1 = max(0.0, target1 - buy_high)
    reward2 = max(0.0, target2 - buy_high)
    rr1 = reward1 / risk_amount if risk_amount else 0.0
    rr2 = reward2 / risk_amount if risk_amount else 0.0

    return {
        "code": code,
        "name": name,
        "trade_date": frame["date"].iloc[-1].strftime("%Y-%m-%d"),
        "reference_close": _round_price(close),
        "recommendation_score": score,
        "validation": {
            "hit_rate": replay.get("hit_rate"),
            "avg_return_pct": replay.get("avg_return_pct"),
        },
        "indicators": {
            "atr14": _round_price(atr14),
            "ma5": _round_price(ma5),
            "ma10": _round_price(ma10),
            "support_5d": _round_price(recent_support),
            "resistance_20d": _round_price(high20),
        },
        "entry": {
            "preferred_pullback_zone": [_round_price(buy_low), _round_price(buy_high)],
            "breakout_trigger": _round_price(breakout),
            "breakout_max_chase": _round_price(max_chase),
            "rules": [
                "回踩区间内缩量企稳后分批，不在开盘急涨时追入",
                "突破买入仅在放量站稳触发价时采用",
                "若开盘价高于突破追价上限，放弃当日买入",
            ],
        },
        "exit": {
            "hard_invalidation": _round_price(stop),
            "take_profit_1": _round_price(target1),
            "take_profit_2": _round_price(target2),
            "rules": [
                "到达第一目标分批止盈，余仓上移保护位",
                "收盘跌破失效位则下一可交易时段退出",
                "买入当日受A股T+1约束，无法卖出",
            ],
        },
        "short_term_operating_range": [_round_price(stop), _round_price(target2)],
        "estimated_entry_risk_pct": round(risk_pct, 2),
        "reward_risk": {
            "entry_basis": "preferred_pullback_zone_high",
            "target_1": round(rr1, 2),
            "target_2": round(rr2, 2),
            "minimum_for_recommendation": 2.0,
            "passes_target_2": rr2 >= 2.0,
        },
    }


def run_trade_plan_job() -> dict[str, Any]:
    cfg = CrawlerConfig()
    recommendations = json.loads((cfg.data_dir / "recommendations/summary.json").read_text(encoding="utf-8"))
    candidates: dict[str, dict[str, Any]] = {}
    for period in ("short", "medium"):
        for item in (recommendations.get("periods", {}).get(period, {}).get("recommendations") or []):
            replay = item.get("replay_summary") or {}
            if (
                float(replay.get("hit_rate") or 0) >= 0.55
                and float(replay.get("avg_return_pct") or 0) >= 1.0
                and int(replay.get("evaluated_count") or 0) >= 500
            ):
                candidates.setdefault(str(item["code"]), item)
    plans = [
        _plan(code, str(item.get("name") or ""), float(item.get("score") or 0), item.get("replay_summary") or {}, _history(cfg, code))
        for code, item in candidates.items()
    ]
    as_of = recommendations.get("market_context", {}).get("trade_date") or now_str()[:10]
    instructions = []
    for plan in plans:
        instructions.append({
            "symbol": plan["code"],
            "as_of": as_of,
            "action": "recommend_buy_zone" if plan.get("reward_risk", {}).get("passes_target_2") else "observe",
            "target_quantity_or_weight": None,
            "order_type": "limit_zone",
            "limit_price_or_trigger": {
                "pullback_zone": (plan.get("entry") or {}).get("preferred_pullback_zone"),
                "breakout_trigger": (plan.get("entry") or {}).get("breakout_trigger"),
                "hard_invalidation": (plan.get("exit") or {}).get("hard_invalidation"),
            },
            "valid_until": as_of,
            "strategy_version": recommendations.get("recommendation_version"),
            "risk_checks": {
                "estimated_entry_risk_pct": plan.get("estimated_entry_risk_pct"),
                "reward_risk": plan.get("reward_risk"),
            },
            "invalidation_reason": "收盘跌破失效位或开盘高于突破追价上限",
            "execution_allowed": False,
            "broker_submission": False,
        })
    payload = {
        "version": "1.1.0",
        "updated_at": now_str(),
        "trade_date": recommendations.get("market_context", {}).get("trade_date"),
        "basis": "five_year_history_plus_five_year_walk_forward_validation",
        "status": "recommendation_ready",
        "instruction_contract_version": INSTRUCTION_CONTRACT_VERSION,
        "instruction_contract_fields": list(FINAL_SYSTEM_OBJECTIVE["instruction_contract"]),
        "product_mode": "recommendation_only",
        "broker_integration": False,
        "plans": plans,
        "instructions": instructions,
        "limitations": [
            "价格区间由历史波动和支撑阻力硬计算，不保证成交或收益",
            "输出供人工参考，系统不连接券商、不自动报单",
            "不包含盘中实时盘口、滑点、个人持仓和风险承受能力",
            "A股T+1使买入当日无法执行止损",
        ],
    }
    _write(cfg.data_dir / "trade_plans" / "summary.json", payload)
    return payload


def build_stock_operation_plan(code: str) -> dict[str, Any]:
    """Build a plan for a manually specified ordinary A-share code."""
    cfg = CrawlerConfig()
    code = str(code)
    stock_path = cfg.data_dir / "stocks" / f"{code}.json"
    validation_path = cfg.data_dir / "strategy_backtest" / f"{code}.json"
    strategy_path = cfg.data_dir / "strategy" / f"{code}.json"
    if not stock_path.exists() or not validation_path.exists() or not strategy_path.exists():
        raise FileNotFoundError(f"{code} 缺少五年历史、策略或验证数据")
    stock = json.loads(stock_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    metric = (validation.get("metrics") or {}).get("20d") or {}
    replay = {
        "hit_rate": metric.get("hit_rate"),
        "avg_return_pct": metric.get("avg_signed_return_pct"),
        "sample_count": metric.get("sample_count"),
        "window_days": validation.get("evaluated_window_days"),
    }
    plan = _plan(
        code,
        str(stock.get("name") or ""),
        float(strategy.get("trend_score") or 0),
        replay,
        _history(cfg, code),
    )
    passed = (
        float(replay.get("hit_rate") or 0) >= 0.55
        and float(replay.get("avg_return_pct") or 0) >= 1.0
        and int(replay.get("sample_count") or 0) >= 500
        and strategy.get("trend_stage") in {"rising", "recovery"}
    )
    plan["decision"] = "candidate" if passed else "observe_or_avoid"
    plan["entry_enabled"] = passed
    plan["decision_reasons"] = [
        f"五年20日验证命中率 {float(replay.get('hit_rate') or 0) * 100:.2f}%",
        f"五年20日平均方向收益 {float(replay.get('avg_return_pct') or 0):.3f}%",
        f"当前趋势阶段 {strategy.get('trend_stage') or 'unknown'}",
        "通过中线硬门槛，可等待价格触发" if passed else "未通过中线硬门槛，价格区间仅作观察",
    ]
    return plan


if __name__ == "__main__":
    run_trade_plan_job()
