"""Agent 配置（P4-1）。"""

from __future__ import annotations

AGENT_VERSION = "1.0.0"
AGENT_DISCLAIMER = "规则型解释输出，非 LLM 推理，不构成投资建议，不触发任何交易。"

# 选股综合分阈值
SCORE_BULLISH = 65
SCORE_BEARISH = 40

# 策略诊断
WEAK_WIN_RATE = 35.0
WEAK_SHARPE = 0.3
HIGH_DRAWDOWN = -40.0
