"""模拟交易任务（P3-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.db_config import DBConfig
from quant_system.config.trading_config import TradingConfig
from quant_system.pipeline.normalizer import normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.trading.simulator import (
    account_summary,
    apply_prediction_rebalance,
    mark_to_market,
    new_account,
)
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import is_research_stock_code
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _load_account(store: JsonStore, cfg: TradingConfig, *, reset: bool = False) -> dict[str, Any]:
    path = store.trading_dir() / "account.json"
    if not reset and path.exists():
        return store.read(path)
    return new_account(cfg.initial_cash)


def _load_stock(store: JsonStore, code: str) -> dict[str, Any]:
    path = store.config.json_data_dir / "stocks" / f"{code}.json"
    if path.exists():
        return store.read(path)
    return {}


def _latest_price(stock: dict[str, Any]) -> float:
    quote = stock.get("quote") or {}
    for value in (quote.get("close"), stock.get("close"), stock.get("close_override")):
        if value is None:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return 0.0


def _tradability(stock: dict[str, Any], price: float, cfg: TradingConfig) -> dict[str, Any]:
    quote = stock.get("quote") or {}
    trade_date = str(stock.get("trade_date") or "")
    kline_date = str(stock.get("kline_date") or "")
    volume = float(quote.get("volume") or 0)
    amount_yi = float(quote.get("amount_yi") or 0)
    change_pct = float(quote.get("change_pct") or 0)
    capacity_value = amount_yi * 100_000_000 * cfg.max_volume_participation_rate
    result: dict[str, Any] = {
        # Amount has consistent currency units across providers; volume may be
        # reported in either shares or lots and is only used for suspension.
        "max_executable_shares": int(capacity_value / price) if price > 0 and capacity_value > 0 else 0,
    }
    if not trade_date or (kline_date and kline_date != trade_date):
        result["buy_reject_reason"] = "stale_quote"
        result["sell_reject_reason"] = "stale_quote"
    elif volume <= 0:
        result["buy_reject_reason"] = "suspended_or_zero_volume"
        result["sell_reject_reason"] = "suspended_or_zero_volume"
    else:
        if change_pct >= cfg.limit_threshold_pct:
            result["buy_reject_reason"] = "limit_up"
        if change_pct <= -cfg.limit_threshold_pct:
            result["sell_reject_reason"] = "limit_down"
    return result


def _risk_exit_reason(pos: dict[str, Any], price: float, cfg: TradingConfig) -> str:
    avg_cost = float(pos.get("avg_cost") or 0)
    pnl = price / avg_cost - 1 if avg_cost > 0 else 0.0
    if pnl <= cfg.stop_loss_pct:
        return "stop_loss"
    if pnl >= cfg.take_profit_pct:
        return "take_profit"
    if int(pos.get("holding_sessions") or 0) >= cfg.max_holding_sessions:
        return "max_holding_period"
    return ""


def _recommendation_items(store: JsonStore) -> list[dict[str, Any]]:
    path = store.recommendation_dir() / "summary.json"
    if not path.exists():
        return []
    payload = store.read(path)
    # Paper trading follows the formal short-horizon strategy. Medium-horizon
    # recommendations remain research context and do not create a second order.
    rows = ((payload.get("periods") or {}).get("short") or {}).get("recommendations") or []
    return [
        row for row in rows
        if row.get("status") == "recommended"
        and is_research_stock_code(str(row.get("code") or ""))
        and "ST" not in str(row.get("name") or "").upper()
    ]


def _resolve_items(
    codes: list[str] | None,
    store: JsonStore,
    account: dict[str, Any],
) -> list[dict[str, Any]]:
    if codes:
        return [{"code": normalize_code(c), "name": ""} for c in codes]
    selected: dict[str, dict[str, Any]] = {
        normalize_code(row["code"]): row for row in _recommendation_items(store)
    }
    # Existing holdings must always remain in scope so they can be marked or
    # exited when a recommendation is withdrawn.
    for code, pos in (account.get("positions") or {}).items():
        selected.setdefault(code, {"code": code, "name": pos.get("name") or code})
    return list(selected.values())


def _strategy_prediction(item: dict[str, Any], *, selected: bool) -> dict[str, Any]:
    score = float(item.get("score") or 0)
    return {
        "code": normalize_code(item["code"]),
        "direction": "up" if selected else "neutral",
        "probability": max(0.0, min(score / 100, 0.90)) if selected else 0.0,
        "confidence": "high" if score >= 80 else "medium" if score >= 70 else "low",
        "source": "formal_short_recommendation",
    }


def run_sim_trade_job(
    codes: list[str] | None = None,
    *,
    reset: bool = False,
    auto_predict: bool = True,
    auto_decision: bool = True,
    initial_cash: float | None = None,
) -> dict[str, Any]:
    """根据决策结果执行虚拟调仓；缺少决策时回退预测。"""
    cfg = TradingConfig(initial_cash=initial_cash or TradingConfig().initial_cash)
    store = JsonStore(DBConfig())
    account = _load_account(store, cfg, reset=reset)
    items = _resolve_items(codes, store, account)

    if not items:
        logger.info("模拟交易暂无正式推荐或已有持仓，仅保存空账户")

    prices: dict[str, float] = {}
    decisions: list[dict[str, Any]] = []
    recommendations = {
        normalize_code(row["code"]): row for row in _recommendation_items(store)
    }
    trade_dates: list[str] = []

    for item in items:
        code = normalize_code(item["code"])
        stock = _load_stock(store, code)
        price = _latest_price(stock)
        if price > 0:
            prices[code] = price
        if stock.get("trade_date"):
            trade_dates.append(str(stock["trade_date"]))

    account = mark_to_market(account, prices)
    trade_date = max(trade_dates) if trade_dates else ""
    same_session = bool(trade_date and account.get("last_rebalance_trade_date") == trade_date)
    if trade_date and not same_session:
        for pos in (account.get("positions") or {}).values():
            pos["holding_sessions"] = int(pos.get("holding_sessions") or 0) + 1

    for item in items:
        code = normalize_code(item["code"])
        stock = _load_stock(store, code)
        name = stock.get("name") or item.get("name") or code
        price = prices.get(code) or _latest_price(stock)
        if price <= 0:
            decisions.append({"code": code, "name": name, "action": "skip", "reason": "missing_price"})
            continue

        before_orders = len(account.get("orders") or [])
        selected = code in recommendations
        pred = _strategy_prediction(recommendations.get(code) or item, selected=selected)
        exit_reason = _risk_exit_reason((account.get("positions") or {}).get(code, {}), price, cfg)
        if exit_reason:
            pred = {**pred, "direction": "neutral", "probability": 0.0}
        if not same_session:
            account = apply_prediction_rebalance(
                account, pred, price=price, name=name, cfg=cfg,
                trade_date=trade_date, tradability=_tradability(stock, price, cfg),
                reason=exit_reason or None,
            )

        after_orders = len(account.get("orders") or [])
        action = "hold"
        if after_orders > before_orders:
            action = str(account["orders"][-1].get("status") or "unknown")
        if same_session:
            action = "marked_only"
        decisions.append({
            "code": code,
            "name": name,
            "action": action,
            "source": "formal_short_recommendation",
            "decision_action": "buy_or_hold" if selected else "exit",
            "position_suggestion": cfg.max_position_pct if selected else 0.0,
            "price": price,
            "direction": pred.get("direction"),
            "probability": pred.get("probability"),
            "confidence": pred.get("confidence"),
            "risk_exit_reason": exit_reason,
        })

    account = mark_to_market(account, prices)
    account["updated_at"] = now_str()
    if trade_date and not same_session:
        account["last_rebalance_trade_date"] = trade_date
    summary = account_summary(account)
    index = {
        "updated_at": account["updated_at"],
        "trade_date": trade_date,
        "mode": "paper_a_share_t1",
        "same_session_mark_only": same_session,
        "risk_policy": {
            "stop_loss_pct": cfg.stop_loss_pct * 100,
            "take_profit_pct": cfg.take_profit_pct * 100,
            "max_holding_sessions": cfg.max_holding_sessions,
            "max_volume_participation_pct": cfg.max_volume_participation_rate * 100,
            "t_plus_1": True,
        },
        "summary": summary,
        "decisions": decisions,
        "positions": list((account.get("positions") or {}).values()),
        "recent_trades": list(account.get("trades") or [])[-50:],
    }
    store.save_trading_account(account)
    store.save_trading_index(index)
    if trade_date:
        store.save_trading_daily(trade_date, index)
    logger.info(
        "模拟交易完成: equity=%s cash=%s positions=%s orders=%s",
        summary["total_equity"], summary["cash"], summary["position_count"], summary["order_count"],
    )
    return index
