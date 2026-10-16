"""极化策略：板块强度与市场情绪共振的高弹性候选（实验性）。"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from quant_system.config.db_config import DBConfig
from quant_system.storage.json_store import JsonStore

def _read(store: JsonStore, rel: str) -> dict[str, Any]:
    path = store.config.json_data_dir / rel
    try:
        return store.read(path) if path.exists() else {}
    except (OSError, ValueError, TypeError):
        return {}

def _main_board(code: str) -> bool:
    return code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))

def _limit_up_candidates(store: JsonStore, market: dict[str, Any], mapping: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """日线可验证的连板实验初筛；盘口项保持 unknown，不伪造。"""
    leaders = {str(x.get("name")): float(x.get("change_pct") or 0) for x in market.get("leading_industries") or []}
    breadth = float((market.get("breadth") or {}).get("advance_ratio") or 0)
    rows: list[dict[str, Any]] = []
    for path in (store.config.json_data_dir / "today_change").glob("[0-9]*.json"):
        item = _read(store, f"today_change/{path.name}")
        code, name = str(item.get("code") or path.stem), str(item.get("name") or "")
        if not _main_board(code) or "ST" in name.upper() or float(item.get("change_pct") or 0) < 9.8:
            continue
        sector = mapping.get(code) or {}
        names = [sector] if isinstance(sector, str) else [sector.get("primary_industry", "")] + list(sector.get("industries") or [])
        sector_change = max((leaders.get(str(x), 0.0) for x in names if x), default=0.0)
        volume_ratio = item.get("volume_ratio_5d")
        amount = float(item.get("amount") or 0)
        if amount < 3e8:
            continue
        amplitude = float(item.get("amplitude_pct") or 0)
        gap = float(item.get("gap_pct") or 0)
        intraday = float(item.get("intraday_pct") or 0)
        score = 25.0
        score += min(15.0, max(0.0, sector_change * 3))
        score += min(10.0, breadth * 10)
        score += min(15.0, max(0.0, (float(volume_ratio or 0) - 0.8) * 10)) if volume_ratio is not None else 0.0
        score += min(15.0, max(0.0, amount / 1e9 * 5))
        score += 12.0 if 0 <= gap <= 5 and intraday >= 3 else (4.0 if gap <= 7 else -8.0)
        score += 8.0 if amplitude <= 8 else -8.0
        missing = ["limit_up_time", "seal_amount", "open_board_count", "auction_volume"]
        rows.append({
            "code": code, "name": name, "trade_date": item.get("trade_date"),
            "sector": names[0] if names else "", "continuation_score": round(max(0, min(100, score)), 2),
            "change_pct": item.get("change_pct"), "gap_pct": gap, "intraday_pct": intraday,
            "amplitude_pct": amplitude, "volume_ratio_5d": volume_ratio,
            "amount_yi": round(amount / 1e8, 2),
            "sector_change_pct": sector_change, "market_advance_ratio": round(breadth, 4),
            "verification_status": "pending_intraday_evidence", "executable": False,
            "missing_intraday_evidence": missing,
            "risk": "次日接力高风险；盘口证据补齐前不可作为买入信号",
        })
    rows.sort(key=lambda x: (x["continuation_score"], x["amount_yi"], x["code"]), reverse=True)
    # 防止单一主题占满候选池；最多保留同一行业两只。
    selected: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    for row in rows:
        sector = str(row.get("sector") or "未知")
        if sector_counts.get(sector, 0) >= 2:
            continue
        selected.append(row)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= max(1, min(limit, 20)):
            break
    return selected

def _forward_review(store: JsonStore, previous: dict[str, Any], current_date: str) -> dict[str, Any]:
    prior_date = str(previous.get("market_trade_date") or "")
    candidates = previous.get("limit_up_candidates") or []
    if not prior_date or prior_date >= current_date or not candidates:
        return {}
    rows = []
    for candidate in candidates:
        code = str(candidate.get("code") or "")
        now = _read(store, f"today_change/{code}.json")
        if str(now.get("trade_date") or "") != current_date:
            continue
        rows.append({"code": code, "name": now.get("name"), "change_pct": float(now.get("change_pct") or 0)})
    if not rows:
        return {}
    return {"signal_date": prior_date, "evaluation_date": current_date, "sample_count": len(rows),
            "positive_rate": round(sum(x["change_pct"] > 0 for x in rows) / len(rows), 4),
            "continued_limit_rate": round(sum(x["change_pct"] >= 9.8 for x in rows) / len(rows), 4),
            "average_return_pct": round(sum(x["change_pct"] for x in rows) / len(rows), 4), "items": rows}

def run_polarized_strategy(limit: int = 10) -> dict[str, Any]:
    store = JsonStore(DBConfig())
    market = _read(store, "today_change/summary.json")
    previous = _read(store, "strategy_iterations/polarized_latest.json")
    mapping = _read(store, "sector_data/stock_industry_map.json").get("stocks") or {}
    leaders = {str(x.get("name")): float(x.get("change_pct") or 0) for x in market.get("leading_industries") or []}
    breadth = market.get("breadth") or {}
    mood = float(breadth.get("advance_ratio") or 0.5) * 100
    # 宇树科技 IPO 事件链：仅作为极化实验主题，不进入正式评分。
    # 名单按公开披露/公告与产业链资料分层，未核验的概念关联不加分。
    robot_chain = {
        "002896": ("减速器", "公开披露关联"), "600580": ("伺服/关节电机", "公开披露关联"),
        "603728": ("电机/控制", "产业链关联"), "002472": ("精密传动", "产业链关联"),
        "603662": ("力矩传感器", "产业链关联"), "603009": ("丝杠/传动", "产业链关联"),
        "003021": ("微型传动/灵巧手", "产业链关联"), "601689": ("结构件/底盘", "产业链关联"),
        "600143": ("轻量化材料", "产业链关联"),
    }
    rows = []
    for path in (store.config.json_data_dir / "strategy").glob("*.json"):
        item = _read(store, f"strategy/{path.name}")
        if item.get("status") != "analyzed":
            continue
        code = str(item.get("code") or path.stem)
        if code.startswith(("688", "30", "8", "4")) or "ST" in str(item.get("name") or "").upper():
            continue
        sector = mapping.get(code) or mapping.get(code[-6:]) or ""
        sector_names = [sector] if isinstance(sector, str) else [sector.get("primary_industry", "")] + list(sector.get("industries") or [])
        sector_change = max((leaders.get(str(name), 0.0) for name in sector_names), default=0.0)
        trend = float(item.get("trend_score") or 0)
        chain = robot_chain.get(code)
        theme_bonus = 8.0 if chain else 0.0
        score = round(0.35 * mood + 0.35 * max(0, min(100, 50 + sector_change * 8)) + 0.30 * trend + theme_bonus, 2)
        rows.append({"code": code, "name": item.get("name"), "sector": sector_names[0] if sector_names else "",
                     "polarized_score": score, "trend_score": trend,
                     "sector_change_pct": sector_change, "market_advance_ratio": round(mood / 100, 4),
                     "robot_chain": chain[0] if chain else None, "robot_chain_evidence": chain[1] if chain else None,
                     "risk": "高波动实验，不作为正式买入信号"})
    rows.sort(key=lambda x: x["polarized_score"], reverse=True)
    market_trade_date = str(market.get("trade_date") or "")
    expected_date = datetime.now().date().isoformat()
    is_fresh = market_trade_date == expected_date
    research_candidates = _limit_up_candidates(store, market, mapping, limit) if is_fresh else []
    actionable_candidates = [
        row for row in research_candidates
        if float(row.get("continuation_score") or 0) >= 75
        and row.get("verification_status") == "verified"
        and row.get("executable") is True
    ]
    payload = {"strategy": "polarized", "experimental": True, "allow_overfit": True,
               "updated_at": datetime.now().isoformat(timespec="seconds"), "market_trade_date": market.get("trade_date"),
               "expected_trade_date": expected_date, "freshness_status": "fresh" if is_fresh else "stale",
               "forward_review": _forward_review(store, previous, market_trade_date),
               "candidates": rows[: max(1, min(limit, 20))] if is_fresh else [],
               "limit_up_candidates": research_candidates,
               "actionable_candidates": actionable_candidates,
               "decision": "trade_candidates_available" if actionable_candidates else "no_trade",
               "decision_reason": None if actionable_candidates else "未同时满足75分、盘口核验和可执行性门槛",
               "promotion_gate": {"min_score": 75, "requires_intraday_evidence": True,
                                  "min_forward_sessions": 20, "min_forward_samples": 100},
               "robot_theme_candidates": [r for r in rows if r.get("robot_chain")][: max(1, min(limit, 20))],
               "event_context": {"name": "宇树科技上市产业链", "status": "待交易所发行日/上市公告确认",
                                 "source_policy": "公开公告优先，媒体供应链名单仅作候选线索"},
               "limitations": (["market_data_stale_candidates_suppressed"] if not is_fresh else []) + ["sector_data_may_be_stale", "not_in_formal_score", "requires_next_day_confirmation", "intraday_limit_up_evidence_missing", "robot_event_date_unverified"]}
    store.write(store.config.json_data_dir / "strategy_iterations/polarized_latest.json", payload)
    if market_trade_date:
        store.write(store.config.json_data_dir / f"strategy_iterations/polarized_history/{market_trade_date}.json", payload)
    return payload
