"""Agent Provider 抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentProvider(ABC):
    name = "base"
    model = "none"
    prompt_version = "none"

    @abstractmethod
    def run(self, evidence: dict[str, Any], *, rule_report: dict[str, Any] | None = None) -> dict[str, Any]:
        """根据证据包生成标准 Agent 输出。"""
