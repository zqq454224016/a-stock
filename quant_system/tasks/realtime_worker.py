"""Detached, deterministic intraday position monitor with Feishu alerts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import fcntl
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any

from quant_system.data_source.stock_sdk_bridge import fetch_minute
from quant_system.data_source.public_http import PublicHttpAPI
from quant_system.notifications.feishu import notify_realtime_advice

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "assets/data/realtime"
CONFIG_PATH = PROJECT_ROOT / "config/position_monitor.json"
INTERVAL = max(15, int(os.getenv("REALTIME_INTERVAL_SEC", "30")))
LOCK_PATH = DATA_ROOT / "worker.lock"
STATE_LABELS = {
    "strong_uptrend": "强势上行", "uptrend": "震荡偏强", "range": "区间震荡",
    "downtrend": "震荡偏弱", "strong_downtrend": "弱势下行",
    "insufficient_data": "数据不足", "unavailable": "行情不可用",
}


def state_label(value: Any) -> str:
    return STATE_LABELS.get(str(value), "未知状态")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def evaluate_kline(rows: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimate the next bars from OHLCV only; never read positions or scores."""
    config = config or {}
    window = max(12, int(config.get("trend_window_bars") or 24))
    usable = [r for r in rows if float(r.get("close") or 0) > 0][-window:]
    if len(usable) < 8:
        return {
            "state": "insufficient_data", "trend": "数据不足", "confidence": 0,
            "outlook": "等待至少8根完整K线后再估计", "priority": "medium",
            "support": None, "resistance": None, "invalidation": "数据不足，不形成方向判断",
        }
    closes = [float(r["close"]) for r in usable]
    highs = [float(r.get("high") or r["close"]) for r in usable]
    lows = [float(r.get("low") or r["close"]) for r in usable]
    volumes = [float(r.get("volume") or 0) for r in usable]
    average_range = sum(h - l for h, l in zip(highs[-10:], lows[-10:])) / min(10, len(usable))
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    prev_ma5 = sum(closes[-6:-1]) / 5
    momentum3 = closes[-1] / closes[-4] - 1 if closes[-4] else 0
    range_high = max(highs[-12:-1] or highs[-12:])
    range_low = min(lows[-12:-1] or lows[-12:])
    span = max(range_high - range_low, closes[-1] * 0.002)
    range_position = (closes[-1] - range_low) / span
    base_volume = sum(volumes[-6:-1]) / max(1, len(volumes[-6:-1]))
    volume_ratio = volumes[-1] / base_volume if base_volume > 0 else 1.0
    score = 0
    score += 2 if closes[-1] > ma5 > ma10 else -2 if closes[-1] < ma5 < ma10 else 0
    score += 1 if ma5 > prev_ma5 else -1
    score += 1 if momentum3 > 0.006 else -1 if momentum3 < -0.006 else 0
    score += 1 if range_position >= 0.8 else -1 if range_position <= 0.2 else 0
    if volume_ratio >= 1.25:
        score += 1 if momentum3 > 0 else -1 if momentum3 < 0 else 0
    if score >= 4:
        state, trend, outlook, priority = "strong_uptrend", "强势上行", "未来1—3根K线偏强，关注突破是否有量能确认", "high"
    elif score >= 2:
        state, trend, outlook, priority = "uptrend", "震荡偏强", "未来1—3根K线倾向延续反弹，但需守住短均线", "normal"
    elif score <= -4:
        state, trend, outlook, priority = "strong_downtrend", "弱势下行", "未来1—3根K线仍有下探风险，反弹未改变弱势结构", "high"
    elif score <= -2:
        state, trend, outlook, priority = "downtrend", "震荡偏弱", "未来1—3根K线偏弱，等待重新站回短均线", "medium"
    else:
        state, trend, outlook, priority = "range", "区间震荡", "方向优势不足，等待突破区间后再判断", "normal"
    confidence = min(85, 50 + abs(score) * 7)
    support = round(min(ma5, closes[-1]) if score > 0 else range_low, 2)
    resistance = round(range_high, 2)
    if score > 0:
        invalidation = f"跌破{support:.2f}且连续两根K线不能收回，偏强预估失效"
    elif score < 0:
        invalidation = f"重新站上{max(ma5, resistance):.2f}且连续两根K线保持，偏弱预估失效"
    else:
        invalidation = f"有效突破{resistance:.2f}或跌破{range_low:.2f}后重新评估"
    return {
        "state": state, "trend": trend, "score": score, "confidence": confidence,
        "outlook": outlook, "priority": priority, "support": support,
        "resistance": resistance, "invalidation": invalidation,
        "features": {"ma5": round(ma5, 3), "ma10": round(ma10, 3),
                     "momentum_3bar_pct": round(momentum3 * 100, 2),
                     "range_position": round(range_position, 3),
                     "volume_ratio": round(volume_ratio, 2),
                     "average_range": round(average_range, 3), "bar_count": len(usable)},
    }


def _trading_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return clock_time(9, 15) <= current <= clock_time(11, 30) or clock_time(13, 0) <= current <= clock_time(15, 5)


def _five_minute_fallback(code: str) -> list[dict[str, Any]]:
    """Aggregate Tencent one-minute fallback into deterministic five-minute OHLCV bars."""
    minute_rows = PublicHttpAPI().fetch_tencent_minutes(code)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in minute_rows:
        stamp = str(row["date"])
        hour, minute = stamp[11:13], int(stamp[14:16])
        key = f"{stamp[:11]}{hour}:{minute // 5 * 5:02d}"
        grouped.setdefault(key, []).append(row)
    bars = []
    for key, chunk in sorted(grouped.items()):
        bars.append({
            "date": key, "time": key, "open": chunk[0]["open"], "close": chunk[-1]["close"],
            "high": max(row["high"] for row in chunk), "low": min(row["low"] for row in chunk),
            "volume": sum(row["volume"] for row in chunk), "amount": sum(row["amount"] for row in chunk),
            "source": "tencent_minute_fallback",
        })
    return bars


def notification_decision(
    advice: dict[str, Any], price: float, old: dict[str, Any], now: datetime,
    config: dict[str, Any], *, bar_id: str = "", force: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Apply value gates, distinct-bar confirmation, cooldown and daily cap."""
    state = dict(old)
    today = now.date().isoformat()
    if state.get("date") != today:
        state = {"date": today, "daily_count": 0}

    observed_state = advice.get("state")
    if state.get("pending_state") != observed_state:
        state["pending_state"] = observed_state
        state["pending_count"] = 0
        state["last_confirmed_bar"] = None
    # Polling the same unfinished 5-minute bar does not count as confirmation.
    if bar_id and state.get("last_confirmed_bar") != bar_id:
        state["pending_count"] = int(state.get("pending_count") or 0) + 1
        state["last_confirmed_bar"] = bar_id

    if force:
        reason = "人工强制测试"
    elif observed_state in {"unavailable", "insufficient_data", "range"}:
        return False, "non_actionable_state", state
    elif float(advice.get("confidence") or 0) < float(config.get("notification_min_confidence") or 64):
        return False, "confidence_below_threshold", state
    elif int(state.get("pending_count") or 0) < int(config.get("notification_confirm_bars") or 2):
        return False, "awaiting_distinct_bar_confirmation", state
    else:
        last_state = state.get("last_notified_state")
        last_price = float(state.get("last_notified_price") or 0)
        move_pct = abs(price / last_price - 1) * 100 if last_price else 0
        resistance = float(advice.get("resistance") or 0)
        support = float(advice.get("support") or 0)
        breakout = observed_state == "strong_uptrend" and resistance > 0 and price >= resistance
        breakdown = observed_state == "strong_downtrend" and support > 0 and price <= support
        if last_state is None:
            reason = "首次形成可执行趋势"
        elif observed_state != last_state:
            reason = f"趋势由{state_label(last_state)}切换为{state_label(observed_state)}"
        elif breakout:
            reason = f"放量突破参考压力{resistance:.2f}"
        elif breakdown:
            reason = f"跌破参考支撑{support:.2f}"
        elif move_pct >= float(config.get("notification_min_price_move_pct") or 2.0):
            reason = f"较上次有效提醒变动{move_pct:.2f}%"
        else:
            return False, "no_material_change", state

    if not force and int(state.get("daily_count") or 0) >= int(config.get("notification_daily_limit") or 3):
        return False, "daily_limit_reached", state
    last_at = state.get("last_notified_at")
    if not force and last_at:
        elapsed = (now - datetime.fromisoformat(last_at)).total_seconds()
        cooldown = int(config.get("notification_cooldown_minutes") or 60) * 60
        if elapsed < cooldown:
            return False, "cooldown_active", state
    state.update({
        "last_notified_at": now.isoformat(timespec="seconds"),
        "last_notified_state": observed_state,
        "last_notified_price": price,
        "daily_count": int(state.get("daily_count") or 0) + 1,
    })
    return True, reason, state


def build_market_context(
    rows: list[dict[str, Any]], api: PublicHttpAPI | None = None, *, code: str = "600206",
) -> dict[str, Any]:
    """Fetch broad indices only for an event that has already passed push gates."""
    api = api or PublicHttpAPI()
    try:
        quotes = api.fetch_tencent_quotes(["sh000001", "sz399001", code])
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)[-160:]}
    by_code = {str(row.get("code")): row for row in quotes}
    sh = by_code.get("000001") or {}
    sz = by_code.get("399001") or {}
    stock_quote = by_code.get(str(code).zfill(6)) or {}
    changes = [float(row["change_pct"]) for row in (sh, sz) if row.get("change_pct") is not None]
    average = sum(changes) / len(changes) if changes else None
    if average is None:
        regime = "未知"
    elif average >= 1:
        regime = "市场强势"
    elif average >= 0.2:
        regime = "市场偏强"
    elif average <= -1:
        regime = "市场弱势"
    elif average <= -0.2:
        regime = "市场偏弱"
    else:
        regime = "市场震荡"

    stock_change = None
    if rows:
        latest = rows[-1]
        latest_day = str(latest.get("date") or latest.get("time") or "")[:10]
        previous = next((row for row in reversed(rows[:-1]) if str(row.get("date") or row.get("time") or "")[:10] != latest_day), None)
        previous_close = float((previous or {}).get("close") or 0)
        current = float(latest.get("close") or 0)
        if previous_close and current:
            stock_change = (current / previous_close - 1) * 100
    if stock_change is None and stock_quote.get("change_pct") is not None:
        stock_change = float(stock_quote["change_pct"])
    relative = stock_change - average if stock_change is not None and average is not None else None
    return {
        "status": "available" if changes else "unavailable", "regime": regime,
        "sh_change_pct": sh.get("change_pct"), "sz_change_pct": sz.get("change_pct"),
        "index_average_change_pct": round(average, 2) if average is not None else None,
        "stock_change_pct": round(stock_change, 2) if stock_change is not None else None,
        "relative_strength_pct": round(relative, 2) if relative is not None else None,
        "relative_label": "强于大盘" if relative is not None and relative >= 0.5 else "弱于大盘" if relative is not None and relative <= -0.5 else "接近大盘",
        "source": "tencent",
    }


def combine_stock_market(advice: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    """Interpret stock K-line direction in its market regime without changing strategy scores."""
    if market.get("status") != "available":
        return {
            "conclusion": advice.get("trend", "未知"), "relation": "大盘数据缺失",
            "market_effect": "不调整个股结论", "confidence": advice.get("confidence", 0),
        }
    score = int(advice.get("score") or 0)
    index_change = float(market.get("index_average_change_pct") or 0)
    relative = float(market.get("relative_strength_pct") or 0)
    volume_ratio = float((advice.get("features") or {}).get("volume_ratio") or 0)
    confidence = int(advice.get("confidence") or 0)
    if score > 0 and index_change >= 0.2:
        return {"conclusion": "个股与大盘共振走强", "relation": "顺势共振",
                "market_effect": "大盘为短线延续提供正向环境", "confidence": min(90, confidence + 5)}
    if score > 0 and index_change <= -0.2:
        if relative >= 1.0 and volume_ratio >= 1.0:
            return {"conclusion": "逆势放量走强", "relation": "逆势强于大盘",
                    "market_effect": "相对强度有效，但市场转弱会放大回撤", "confidence": confidence}
        return {"conclusion": "个股反弹但受大盘压制", "relation": "逆势弱确认",
                "market_effect": "缺少量能或超额强度，不能按强趋势处理", "confidence": max(40, confidence - 15)}
    if score < 0 and index_change <= -0.2:
        return {"conclusion": "个股与大盘共振走弱", "relation": "弱势共振",
                "market_effect": "系统性风险增强，下探预估获得确认", "confidence": min(90, confidence + 5)}
    if score < 0 and index_change >= 0.2:
        return {"conclusion": "大盘偏强但个股独弱", "relation": "显著弱于大盘",
                "market_effect": "弱势主要来自个股自身，反弹质量更差", "confidence": min(90, confidence + 5)}
    return {"conclusion": advice.get("trend", "区间震荡"), "relation": "大盘中性",
            "market_effect": "指数未形成明显推动或压制", "confidence": confidence}


def build_trade_plan(advice: dict[str, Any], combined: dict[str, Any], price: float) -> dict[str, Any]:
    """Create conditional, position-agnostic buy/sell levels from K-line structure."""
    features = advice.get("features") or {}
    support = float(advice.get("support") or price)
    resistance = float(advice.get("resistance") or price)
    average_range = float(features.get("average_range") or price * 0.006)
    buffer = max(price * 0.002, average_range * 0.2, 0.01)
    score = int(advice.get("score") or 0)
    confidence = int(combined.get("confidence", advice.get("confidence") or 0))
    breakout = round(resistance + buffer, 2)
    pullback_low = round(support, 2)
    pullback_high = round(support + buffer, 2)
    failure = round(support - buffer, 2)
    recovery = round(resistance + buffer, 2)
    if score > 0 and confidence >= 64 and combined.get("relation") != "逆势弱确认":
        risk = max(breakout - failure, price * 0.008)
        return {
            "bias": "进攻", "action": "满足其一可考虑买入，不满足不追",
            "breakout_buy": breakout,
            "pullback_buy_zone": [pullback_low, pullback_high],
            "buy_confirmation": "突破后连续两根5分钟K线站稳，或回踩区缩量止跌后重新站上MA5",
            "sell_trigger": failure, "stop_loss": failure,
            "target_1": round(breakout + risk, 2), "target_2": round(breakout + risk * 2, 2),
        }
    if score < 0 or combined.get("relation") == "逆势弱确认":
        return {
            "bias": "防守", "action": "反弹减仓或跌破卖出，不以持有替代风控",
            "rebound_sell_zone": [round(max(support, resistance - average_range), 2), round(resistance, 2)],
            "sell_trigger": failure, "stop_loss": failure,
            "reentry_trigger": recovery,
            "reentry_confirmation": "重新站上压力位并连续两根5分钟K线保持，且量比不低于1",
        }
    return {
        "bias": "等待", "action": "区间内不交易，突破买、跌破卖",
        "breakout_buy": breakout, "sell_trigger": failure,
    }


def run_once(config: dict[str, Any] | None = None, *, force_notify: bool = False) -> dict[str, Any]:
    config = config or _read(CONFIG_PATH)
    if config.get("push_scope", "single_stock") != "single_stock":
        raise ValueError("实时推送仅允许单只股票模式")
    code = str(config.get("code") or "600206")
    symbol = f"{code}.{'SH' if code.startswith(('5', '6', '9')) else 'SZ'}"
    frame = fetch_minute(symbol, period=5)
    rows = frame.tail(240).to_dict(orient="records") if not frame.empty else []
    quote_source = "stock-sdk"
    if not rows:
        try:
            rows = _five_minute_fallback(code)[-240:]
            quote_source = "tencent_minute_fallback"
        except Exception:
            rows = []
            quote_source = "unavailable"
    latest = rows[-1] if rows else {}
    # Never turn a configured reference price into a fake real-time quote.
    price = float(latest.get("close") or 0)
    advice = evaluate_kline(rows, config) if rows else {
        "state": "unavailable", "trend": "不可用", "confidence": 0,
        "outlook": "实时K线不可用，不形成走势预估", "priority": "critical",
        "support": None, "resistance": None, "invalidation": "等待数据恢复",
    }
    now = datetime.now()
    payload = {
        "code": code, "name": config.get("name") or code, "symbol": symbol,
        "updated_at": now.isoformat(timespec="seconds"),
        "source": quote_source,
        "realtime": bool(rows), "latest": latest or {"close": price}, "rows": rows[-60:],
        "analysis": {**advice, "state_label": state_label(advice.get("state")),
                     "status": "有效" if price else "不可用"},
        "analysis_basis": "deterministic_kline_only",
        "execution_allowed": False, "paper_or_notification_only": True,
    }
    state_path = DATA_ROOT / f"{code}_notification_state.json"
    old_state = _read(state_path)
    if not rows:
        payload["feishu"] = {"status": "skipped", "reason": "realtime_kline_unavailable"}
    else:
        bar_id = str(latest.get("date") or latest.get("time") or latest.get("timestamp") or "")
        should_send, reason, new_state = notification_decision(
            advice, price, old_state, now, config, bar_id=bar_id, force=force_notify,
        )
        payload["notification_reason"] = reason
        if should_send:
            payload["market_context"] = build_market_context(rows, code=code)
            payload["combined_analysis"] = combine_stock_market(advice, payload["market_context"])
            payload["trade_plan"] = build_trade_plan(advice, payload["combined_analysis"], price)
            payload["feishu"] = notify_realtime_advice(code, payload)
        else:
            payload["feishu"] = {"status": "skipped", "reason": reason}
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / f"{code}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_forever() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return
    try:
        while True:
            try:
                if _trading_window(datetime.now()):
                    run_once()
                    time.sleep(INTERVAL)
                else:
                    time.sleep(60)
            except Exception as exc:
                (DATA_ROOT / "worker_error.json").write_text(json.dumps({"updated_at": datetime.now().isoformat(timespec="seconds"), "error": str(exc)}, ensure_ascii=False), encoding="utf-8")
                time.sleep(60)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
        (DATA_ROOT / "worker.pid").unlink(missing_ok=True)


def launch_realtime_worker() -> dict[str, Any]:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    pid_path = DATA_ROOT / "worker.pid"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            return {"status": "already_running", "pid": pid}
        except (OSError, ValueError):
            pid_path.unlink(missing_ok=True)
    log = (DATA_ROOT / "worker.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "quant_system.tasks.realtime_worker", "--daemon"],
        cwd=str(PROJECT_ROOT), stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True, close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {"status": "started", "pid": process.pid}


if __name__ == "__main__":
    run_forever()
