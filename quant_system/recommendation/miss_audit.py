"""对抗漏检审计：解释大涨票为何未进正式推荐，区分设计拒绝与管线缺陷。"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_miss_audit(
    period_results: dict[str, Any],
    context: dict[str, Any],
    *,
    gainer_floor_pct: float = 5.0,
    example_codes: tuple[str, ...] = ("600869", "002406"),
    top_n: int = 8,
) -> dict[str, Any]:
    short = (period_results.get("short") or {})
    evaluated = list(short.get("evaluated") or [])
    class_counts: Counter[str] = Counter()
    numerical_ready = 0
    intraday_missing = 0
    anti_chase = 0
    gainers: list[dict[str, Any]] = []

    for row in evaluated:
        daily = row.get("daily_filter") or {}
        exclusion = daily.get("exclusion") or {}
        for label in exclusion.get("classes") or []:
            class_counts[str(label)] += 1
        if exclusion.get("numerical_passed"):
            numerical_ready += 1
        if "intraday_missing" in (exclusion.get("classes") or []):
            intraday_missing += 1
        if exclusion.get("design_anti_chase"):
            anti_chase += 1
        change = _f((daily.get("values") or {}).get("change_pct"), -999)
        if change >= gainer_floor_pct:
            gainers.append({
                "code": row.get("code"),
                "name": row.get("name"),
                "change_pct": change,
                "float_cap_yi": (daily.get("values") or {}).get("float_cap_yi"),
                "exclusion_classes": exclusion.get("classes") or [],
                "numerical_blockers": exclusion.get("numerical_blockers") or [],
                "design_anti_chase": bool(exclusion.get("design_anti_chase")),
                "numerical_passed": bool(exclusion.get("numerical_passed")),
            })

    gainers.sort(key=lambda item: item["change_pct"], reverse=True)
    examples: list[dict[str, Any]] = []
    by_code = {str(row.get("code")): row for row in evaluated}
    for code in example_codes:
        row = by_code.get(code)
        if not row:
            continue
        daily = row.get("daily_filter") or {}
        exclusion = daily.get("exclusion") or {}
        values = daily.get("values") or {}
        examples.append({
            "code": code,
            "name": row.get("name"),
            "change_pct": values.get("change_pct"),
            "float_cap_yi": values.get("float_cap_yi"),
            "limits": daily.get("limits"),
            "exclusion_classes": exclusion.get("classes") or [],
            "numerical_blockers": exclusion.get("numerical_blockers") or [],
            "verdict": (
                "design_anti_chase_exclusion"
                if exclusion.get("design_anti_chase")
                else "structure_or_liquidity_exclusion"
                if exclusion.get("numerical_blockers")
                else "intraday_or_pipeline"
            ),
            "why_not_recommended": (
                "弱势板要求温和涨幅带内确认，不追当日已大幅冲高的票；"
                "另需市值/均线/量能与分时同时通过。"
                if exclusion.get("design_anti_chase")
                else "涨幅/市值/换手/均线/放量等量价硬条件未过；涨得多不是入选理由。"
                if exclusion.get("numerical_blockers")
                else "量价已过，卡在分时确认。"
            ),
        })

    numerical_ready_missing_intraday = 0
    for row in evaluated:
        daily = row.get("daily_filter") or {}
        exclusion = daily.get("exclusion") or {}
        if exclusion.get("numerical_passed") and "intraday_missing" in (exclusion.get("classes") or []):
            numerical_ready_missing_intraday += 1
    # 管线缺陷：量价已过的票仍整批缺分时（未拉取），而非「全市场未拉分钟线」的正常失败关闭。
    pipeline_defect = numerical_ready > 0 and numerical_ready_missing_intraday == numerical_ready
    return {
        "regime": context.get("regime"),
        "evaluated_count": len(evaluated),
        "recommendation_count": len(short.get("recommendations") or []),
        "numerical_ready_count": numerical_ready,
        "numerical_ready_missing_intraday": numerical_ready_missing_intraday,
        "intraday_missing_count": intraday_missing,
        "anti_chase_exclusion_count": anti_chase,
        "exclusion_class_counts": dict(class_counts.most_common()),
        "pipeline_intraday_defect": pipeline_defect,
        "top_gainers_excluded": gainers[:top_n],
        "examples": examples,
        "promotion_alignment": {
            "same_day_chase_is_not_promotion_target": True,
            "research_entry": "prior_signal_then_t1_open",
            "note": (
                "远东这类当日大涨票被排除，是正式推荐反追涨设计，"
                "不是晋级门槛误杀；研究侧应抓先验信号日，而非收盘后追涨。"
            ),
        },
    }
