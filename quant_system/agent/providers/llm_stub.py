"""LLM Provider 占位实现。

当前环境不强制配置外部模型；未实现真实调用时显式失败，由任务层降级到规则 Provider。
"""

from __future__ import annotations

from typing import Any

from quant_system.agent.providers.base import AgentProvider
from quant_system.config.agent_config import AGENT_PROMPT_VERSION


class LLMStubProvider(AgentProvider):
    name = "llm"
    model = "external-llm-unconfigured"
    prompt_version = AGENT_PROMPT_VERSION

    def run(self, evidence: dict[str, Any], *, rule_report: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError("LLM provider 未配置，已降级为规则型 Agent")
