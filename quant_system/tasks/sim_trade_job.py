"""模拟交易任务（P3-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.db_config import DBConfig
from quant_system.config.trading_config import TradingConfig
from quant_system.pipeline.normalizer import load_watchlist, normalize_code
from quant_system.storage.json_store import JsonStore
from quant_system.tasks.decision_job import run_decision_job
from quant_system.tasks.predict_job import run_predict_job
from quant_system.trading.simulator import (
    account_summary,
    apply_decision_rebalance,
    apply_prediction_rebalance,
    mark_to_market,
    new_account,
)
from quant_system.utils.logger import get_logger
from quant_system.utils.market_scope import filter_research_stocks
from quant_system.utils.time_utils import now_str

logger = get_logger(__name__)


def _load_account(store: JsonStore, cfg: TradingConfig, *, reset: bool = False) -> dict[str, Any]:
    path = store.trading_dir() / "account.json"
    if not reset and path.exists():
        return store.read(path)
    return new_account(cfg.initial_cash)


def _load_prediction(store: JsonStore, code: str) -> dict[str, Any] | None:
    path = store.predictions_dir() / f"{code}.json"
    if path.exists():
        return store.read(path)
    return None


def _load_decision(store: JsonStore, code: str) -> dict[str, Any] | None:
    path = store.decisions_dir() / f"{code}.json"
    if path.exists():
        return store.read(path)
    return None


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


def _resolve_items(codes: list[str] | None, cfg: CrawlerConfig) -> list[dict[str, str]]:
    if codes:
        return [{"code": normalize_code(c), "name": ""} for c in codes]
    return filter_research_stocks(load_watchlist(cfg), cfg, reason="模拟交易")


def run_sim_trade_job(
    codes: list[str] | None = None,
    *,
    reset: bool = False,
    auto_predict: bool = True,
    auto_decision: bool = True,
    initial_cash: float | None = None,
) -> dict[str, Any]:
    """根据决策结果执行虚拟调仓；缺少决策时回退预测。"""
    crawler_cfg = CrawlerConfig()
    cfg = TradingConfig(initial_cash=initial_cash or TradingConfig().initial_cash)
    store = JsonStore(DBConfig())
    items = _resolve_items(codes, crawler_cfg)

    if not items:
        logger.error("未配置自选股")
        return {}

    account = _load_account(store, cfg, reset=reset)
    prices: dict[str, float] = {}
    decisions: list[dict[str, Any]] = []

    for item in items:
        code = normalize_code(item["code"])
        stock = _load_stock(store, code)
        price = _latest_price(stock)
        if price > 0:
            prices[code] = price

    account = mark_to_market(account, prices)

    for item in items:
        code = normalize_code(item["code"])
        stock = _load_stock(store, code)
        name = stock.get("name") or item.get("name") or code
        price = prices.get(code) or _latest_price(stock)
        if price <= 0:
            decisions.append({"code": code, "name": name, "action": "skip", "reason": "missing_price"})
            continue

        before_orders = len(account.get("orders") or [])
        decision = _load_decision(store, code)
        if not decision and auto_decision:
            run_decision_job(codes=[code], auto_predict=auto_predict)
            decision = _load_decision(store, code)

        pred = None
        if decision:
            account = apply_decision_rebalance(account, decision, price=price, name=name, cfg=cfg)
        else:
            pred = _load_prediction(store, code)
            if not pred and auto_predict:
                run_predict_job(codes=[code])
                pred = _load_prediction(store, code)
            if not pred:
                decisions.append({"code": code, "name": name, "action": "skip", "reason": "missing_decision_prediction"})
                continue
            account = apply_prediction_rebalance(account, pred, price=price, name=name, cfg=cfg)

        after_orders = len(account.get("orders") or [])
        action = "filled" if after_orders > before_orders else "hold"
        source = "decision" if decision else "prediction"
        decisions.append({
            "code": code,
            "name": name,
            "action": action,
            "source": source,
            "decision_action": (decision or {}).get("action"),
            "position_suggestion": (decision or {}).get("position_suggestion"),
            "price": price,
            "direction": (decision or {}).get("evidence", {}).get("prediction", {}).get("direction") or (pred or {}).get("direction"),
            "probability": (decision or {}).get("evidence", {}).get("prediction", {}).get("probability") or (pred or {}).get("probability"),
            "confidence": (decision or pred or {}).get("confidence"),
        })

    account = mark_to_market(account, prices)
    account["updated_at"] = now_str()
    summary = account_summary(account)
    index = {
        "updated_at": account["updated_at"],
        "summary": summary,
        "decisions": decisions,
        "positions": list((account.get("positions") or {}).values()),
    }
    store.save_trading_account(account)
    store.save_trading_index(index)
    logger.info(
        "模拟交易完成: equity=%s cash=%s positions=%s orders=%s",
        summary["total_equity"], summary["cash"], summary["position_count"], summary["order_count"],
    )
    return index
