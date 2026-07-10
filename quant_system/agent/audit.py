"""Agent 审计记录。"""

from __future__ import annotations

from typing import Any

from quant_system.config.agent_config import AGENT_REPORT_SCHEMA_VERSION
from quant_system.utils.time_utils import now_str


def build_agent_audit_record(
    *,
    code: str,
    provider: str,
    evidence: dict[str, Any],
    output: dict[str, Any],
    policy: dict[str, Any],
    fallback_reason: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": AGENT_REPORT_SCHEMA_VERSION,
        "code": code,
        "provider": provider,
        "model": output.get("model"),
        "prompt_version": output.get("prompt_version"),
        "updated_at": now_str(),
        "fallback_reason": fallback_reason,
        "input_summary": {
            "task": evidence.get("task"),
            "trade_date": evidence.get("trade_date"),
            "allowed_actions": evidence.get("allowed_actions") or [],
            "missing_inputs": evidence.get("missing_inputs") or [],
            "inputs_used": evidence.get("inputs_used") or [],
        },
        "output_summary": {
            "summary": output.get("summary"),
            "direction_view": output.get("direction_view"),
            "confidence": output.get("confidence"),
            "suggested_actions": output.get("suggested_actions") or [],
            "requires_human_review": output.get("requires_human_review"),
        },
        "policy": policy,
        "replayable": True,
    }
