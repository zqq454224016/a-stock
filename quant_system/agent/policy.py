"""Agent 输出权限与合规校验。"""

from __future__ import annotations

from typing import Any

FORBIDDEN_TERMS = (
    "自动下单",
    "直接下单",
    "绕过风控",
    "无需人工确认",
    "必涨",
    "必跌",
)


def validate_agent_output(result: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    text_parts = [
        result.get("summary", ""),
        " ".join(result.get("suggested_actions") or []),
        " ".join(result.get("evidence") or []),
    ]
    joined = " ".join(str(x) for x in text_parts)

    for term in FORBIDDEN_TERMS:
        if term in joined:
            violations.append(f"输出包含禁止表述：{term}")

    allowed = set(evidence.get("allowed_actions") or [])
    if not {"analyze", "summarize"}.issubset(allowed):
        violations.append("证据包缺少只读分析权限")

    if not result.get("evidence"):
        violations.append("输出缺少证据引用")
    if not result.get("risks"):
        violations.append("输出缺少风险说明")

    actions = result.get("suggested_actions") or []
    if any(("买入" in x or "卖出" in x or "减仓" in x) for x in actions):
        if result.get("requires_human_review") is not True:
            violations.append("涉及交易动作但未要求人工确认")

    return {
        "passed": not violations,
        "violations": violations,
        "allowed_actions": sorted(allowed),
    }
