"""Deterministic point-in-time quality gate for the long-term strategy."""
from __future__ import annotations
from typing import Any

REQUIRED = ("revenue_growth", "profit_growth", "operating_cash_flow", "debt_to_assets")

def quality_gate(facts: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED if facts.get(key) is None]
    if missing:
        return {"passed": False, "score": None, "missing": missing, "reason": "point_in_time_fields_missing"}
    checks = {
        "revenue_growth": float(facts["revenue_growth"]) > 0,
        "profit_growth": float(facts["profit_growth"]) > 0,
        "operating_cash_flow": float(facts["operating_cash_flow"]) > 0,
        "debt_to_assets": float(facts["debt_to_assets"]) < 0.75,
    }
    return {"passed": all(checks.values()), "score": round(sum(checks.values()) / 4 * 100, 2), "missing": [], "checks": checks}

def exit_on_quality_break(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev, now = quality_gate(previous), quality_gate(current)
    if now["missing"]:
        return {"exit": False, "reason": "await_verified_point_in_time_data"}
    deteriorated = (float(current["revenue_growth"]) < float(previous.get("revenue_growth", 0))
                    and float(current["profit_growth"]) < float(previous.get("profit_growth", 0))
                    and float(current["operating_cash_flow"]) < 0)
    return {"exit": bool(prev.get("passed") and deteriorated), "reason": "confirmed_quality_break" if deteriorated else "no_confirmed_break"}
