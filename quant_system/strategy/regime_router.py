"""统一的市场状态路由与防守/反转/反向 ETF 信号契约。

该模块只负责决定“哪条策略有资格工作”，不替代评分，也不凭空生成 ETF
代码。ETF 候选必须由行情源提供日线、流动性和产品方向元数据后再进入回测。
"""

from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_regime(context: dict[str, Any]) -> str:
    """把市场状态压缩为可路由的四态，而不是把所有策略同时打开。"""
    regime = str(context.get("regime") or "").strip()
    avg = _num(context.get("index_avg_change_pct"))
    breadth = _num((context.get("sentiment") or {}).get("breadth"))
    if regime == "偏强" and (avg is None or avg >= 0.5) and (breadth is None or breadth >= 0):
        return "strong_uptrend"
    if regime == "偏弱" or (avg is not None and avg <= -0.8) or (breadth is not None and breadth <= -0.2):
        return "strong_downtrend"
    if avg is not None and avg < 0:
        return "weak_range"
    return "range"


ROUTES: dict[str, dict[str, Any]] = {
    "strong_uptrend": {
        "label": "强势上行",
        "enabled": ["long_quality", "swing_trend", "short_3_5", "ultra_1_2", "tail_t1"],
        "disabled": ["inverse_etf"],
        "cash_floor": 0.20,
    },
    "range": {
        "label": "区间震荡",
        "enabled": ["long_quality", "short_3_5", "reversal_confirmed"],
        "disabled": ["aggressive_breakout", "inverse_etf"],
        "cash_floor": 0.50,
    },
    "weak_range": {
        "label": "震荡偏弱",
        "enabled": ["defensive_etf", "reversal_confirmed"],
        "disabled": ["short_3_5", "ultra_1_2", "aggressive_breakout"],
        "cash_floor": 0.70,
    },
    "strong_downtrend": {
        "label": "弱势下行",
        "enabled": ["defensive_etf", "inverse_etf", "reversal_confirmed"],
        "disabled": ["long_quality", "short_3_5", "ultra_1_2", "tail_t1", "aggressive_breakout"],
        "cash_floor": 0.85,
    },
}


def route(context: dict[str, Any]) -> dict[str, Any]:
    state = classify_regime(context)
    spec = ROUTES[state]
    return {
        "state": state,
        "label": spec["label"],
        "enabled": list(spec["enabled"]),
        "disabled": list(spec["disabled"]),
        "cash_floor": spec["cash_floor"],
        "principle": "先确定市场状态，再允许对应持有周期的策略参与；不以放宽门槛凑推荐",
    }


# 路由表里的策略键 → 证据矩阵（strategy_tracks/latest.json）里的轨道或具体策略。
ROUTE_EVIDENCE = {
    "long_quality": {"track": "long"},
    "swing_trend": {"track": "long"},
    "short_3_5": {"track": "short_3_5"},
    "aggressive_breakout": {"track": "short_3_5"},
    "ultra_1_2": {"track": "ultra_1_2"},
    "tail_t1": {"track": "ultra_1_2"},
    "defensive_etf": {"strategies": ("def_rotation_down", "def_rotation_always")},
    "reversal_confirmed": {"strategies": ("rev_confirmed_hs300_h5",)},
    "inverse_etf": {"unavailable": "A股场内无反向/杠杆ETF"},
}
STATE_TO_EVIDENCE_REGIME = {
    "strong_uptrend": "rising", "range": "range", "weak_range": "range", "strong_downtrend": "falling",
}
REVERSAL_STRATEGIES = {
    "rev_oversold_hs300_h3": {"etf": "510300", "label": "沪深300ETF", "hold_days": 3},
    "rev_oversold_hs300_h5": {"etf": "510300", "label": "沪深300ETF", "hold_days": 5},
    "rev_oversold_cyb_h5": {"etf": "159915", "label": "创业板ETF", "hold_days": 5},
}


def apply_evidence(routed: dict[str, Any], evidence: dict[str, Any] | None, context: dict[str, Any]) -> dict[str, Any]:
    """静态启停表 ∩ 分市场状态证据；没有证据的策略即使表里允许也不启用。"""
    result = dict(routed)
    if not evidence or evidence.get("status") != "complete":
        result["evidence"] = {"status": "missing", "note": "缺少 strategy_tracks 证据，按静态表仅作观察"}
        result["evidence_enabled"] = []
        return result
    current = evidence.get("current") or {}
    regime = STATE_TO_EVIDENCE_REGIME.get(routed.get("state"), "range")
    if current.get("date") and str(current.get("date")) == str(context.get("trade_date")):
        regime = str(current.get("regime") or regime)  # 同一交易日时以全市场广度口径为准
    tracks = evidence.get("tracks") or {}
    strategies = evidence.get("strategies") or {}

    def strategy_passed(name: str, at: str) -> bool:
        return bool((((strategies.get(name) or {}).get("by_regime") or {}).get(at) or {}).get("evidence_passed"))

    enabled, blocked = [], []
    for key in routed.get("enabled") or []:
        rule = ROUTE_EVIDENCE.get(key, {})
        if "unavailable" in rule:
            ok, reason = False, rule["unavailable"]
        elif "track" in rule:
            view = (((tracks.get(rule["track"]) or {}).get("by_regime") or {}).get(regime) or {})
            ok = bool(view.get("active"))
            reason = None if ok else f"{rule['track']} 在 {regime} 状态无通过证据"
        else:
            ok = any(strategy_passed(name, regime) for name in rule.get("strategies", ()))
            reason = None if ok else f"{'/'.join(rule.get('strategies', ()))} 在 {regime} 状态无通过证据"
        (enabled if ok else blocked).append(key if ok else {"route": key, "reason": reason})

    # 超跌反转条件由证据任务按收盘数据逐项计算；尾盘实盘需用实时价复核同样的4项。
    setups = current.get("reversal_setups") or {}
    reversals = []
    for name, meta in REVERSAL_STRATEGIES.items():
        if not strategy_passed(name, regime):
            continue
        setup = setups.get(meta["etf"]) or {}
        reversals.append({
            "strategy": name, "etf": meta["etf"], "label": meta["label"], "hold_days": meta["hold_days"],
            "setup_passed": bool(setup.get("passed")), "conditions_met": setup.get("met"),
            "conditions": setup.get("conditions"), "as_of": setup.get("date"),
            "rule": f"价格偏离/抛压持续/成交放大/盘中承接 4项满足≥3项时尾盘买入，持{meta['hold_days']}个交易日收盘卖出",
        })
    active_reversal = any(item["setup_passed"] for item in reversals)
    result.update({
        "evidence": {"status": "applied", "regime": regime, "updated_at": evidence.get("updated_at")},
        "evidence_enabled": enabled,
        "blocked_by_evidence": blocked,
        "reversal_setups": reversals,
        "evidence_cash_floor": routed.get("cash_floor") if enabled or active_reversal else 1.0,
        "evidence_summary": (
            "有证据的策略：" + "、".join(enabled) if enabled
            else "超跌反转条件成立，可按反转ETF规则尾盘建仓" if active_reversal
            else "当前状态下没有通过证据的多头策略，新开仓保持现金；超跌反转有证据但条件未成立" if reversals
            else "当前状态下没有任何通过证据的策略（含超跌反转），新开仓保持现金"
        ),
    })
    return result


def etf_signal(row: dict[str, Any], *, state: str, product_type: str) -> dict[str, Any]:
    """评估已经明确产品类型的 ETF；缺字段时失败关闭。"""
    required = ("close", "ma20", "ma60", "volume_ratio")
    missing = [key for key in required if _num(row.get(key)) is None]
    if missing:
        return {"passed": False, "signal": "unavailable", "missing": missing, "reasons": ["ETF行情字段不足"]}
    close, ma20, ma60 = (_num(row[x]) for x in ("close", "ma20", "ma60"))
    volume_ratio = _num(row["volume_ratio"])
    if product_type == "defensive":
        passed = state in {"weak_range", "strong_downtrend", "range"} and close >= ma20 and ma20 >= ma60 and volume_ratio >= 0.8
        return {"passed": passed, "signal": "defensive_hold" if passed else "wait", "reasons": ["低波动/债券/黄金等防守ETF需自身保持上升结构"]}
    if product_type == "reversal":
        ret5 = _num(row.get("ret5"))
        rsi = _num(row.get("rsi14"))
        passed = state in {"weak_range", "strong_downtrend", "range"} and close > ma20 and (ret5 is not None and ret5 > 0) and (rsi is None or rsi >= 45)
        return {"passed": passed, "signal": "confirmed_reversal" if passed else "wait", "reasons": ["反转必须重新站回MA20，不能仅凭超跌买入"]}
    if product_type == "inverse":
        passed = state == "strong_downtrend" and close > ma20 and ma20 >= ma60 and volume_ratio >= 1.0
        return {"passed": passed, "signal": "inverse_trend" if passed else "wait", "reasons": ["反向ETF只在强下行且产品本身趋势向上时观察"]}
    return {"passed": False, "signal": "unavailable", "missing": ["unknown_product_type"], "reasons": []}

