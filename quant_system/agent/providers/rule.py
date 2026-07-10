"""规则型 Agent Provider。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.providers.base import AgentProvider
from quant_system.config.agent_config import AGENT_PROMPT_VERSION


class RuleAgentProvider(AgentProvider):
    name = "rule"
    model = "local-rule"
    prompt_version = AGENT_PROMPT_VERSION

    def run(self, evidence: dict[str, Any], *, rule_report: dict[str, Any] | None = None) -> dict[str, Any]:
        report = rule_report or {}
        selection = report.get("stock_selection") or {}
        review = report.get("prediction_review") or {}
        diagnosis = report.get("strategy_diagnosis") or {}
        risks = list(dict.fromkeys(
            (selection.get("risks") or [])
            + (review.get("failure_conditions") or [])
            + (diagnosis.get("risks") or [])
            + (report.get("limitations") or [])
        ))
        evidence_items = list(dict.fromkeys(
            (selection.get("evidence") or [])
            + (selection.get("drivers") or [])
            + (diagnosis.get("findings") or [])[:3]
            + (review.get("notes") or [])[:3]
        ))
        direction = {
            "positive": "bullish",
            "negative": "bearish",
        }.get(selection.get("verdict"), "neutral")
        return {
            "provider": self.name,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "summary": report.get("summary") or "中性观察",
            "direction_view": direction,
            "confidence": report.get("confidence") or "low",
            "evidence": evidence_items or ["本地规则报告已生成"],
            "risks": risks or ["无额外风险标记"],
            "failure_conditions": review.get("failure_conditions") or ["证据包关键字段变化时重新评估"],
            "suggested_actions": ["仅用于研究解释", "进入人工复核后再考虑操作"],
            "forbidden_actions": ["不得自动下单", "不得绕过风控", "不得修改生产参数"],
            "requires_human_review": True,
            "raw_output": {"source": "rule_report", "missing_inputs": evidence.get("missing_inputs") or []},
        }
