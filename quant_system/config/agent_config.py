"""Agent 配置（P4-1/P4-2）。"""

from __future__ import annotations

AGENT_VERSION = "1.1.0"
AGENT_REPORT_SCHEMA_VERSION = "1.0.0"
AGENT_PROMPT_VERSION = "stock_review_v1.0.0"
AGENT_DISCLAIMER = "Agent 解释输出，不构成投资建议，不触发任何交易；涉及操作必须经过风控与人工确认。"

# 选股综合分阈值
SCORE_BULLISH = 65
SCORE_BEARISH = 40

# 策略诊断
WEAK_WIN_RATE = 35.0
WEAK_SHARPE = 0.3
HIGH_DRAWDOWN = -40.0
