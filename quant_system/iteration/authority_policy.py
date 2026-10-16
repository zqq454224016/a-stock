"""Hard authority boundary between humans, AI data processing and deterministic engines."""

from __future__ import annotations

from typing import Any

POLICY_VERSION = "1.1.0"

HUMAN_DECISIONS = [
    {
        "id": "H001",
        "decision": "购买、升级或接受外部数据服务协议",
        "reason": "涉及费用、合同、账号授权与外部法律关系",
    },
    {
        "id": "H002",
        "decision": "修改评分公式、因子权重、晋级阈值或风险预算",
        "reason": "会改变研究结论与风险承担，AI不得影响评分",
    },
    {
        "id": "H003",
        "decision": "将研究策略晋级为正式推荐策略",
        "reason": "策略可通过硬门槛，但启用正式推荐必须人工确认",
    },
    {
        "id": "H004",
        "decision": "是否恢复券商自动交易（当前方案已放弃）",
        "reason": "当前产品范围仅推荐策略；若未来恢复自动交易须重新立项并人工授权",
    },
    {
        "id": "H005",
        "decision": "解除熔断、覆盖急停或接受重大数据质量例外",
        "reason": "属于安全边界例外，不允许自动放宽",
    },
    {
        "id": "H006",
        "decision": "根据系统推荐自行下单或忽略",
        "reason": "真实买卖由人工在券商客户端完成，系统不下单",
    },
]

AI_ALLOWED = [
    "发现和验证数据来源",
    "解析公告、PDF及其他非结构化数据",
    "字段映射、时间语义标注、版本识别与异常版式处理",
    "数据缺口分析、采集方案生成、失败原因分类与回退建议",
]

AI_FORBIDDEN = [
    "生成或修改评分公式",
    "调整因子权重、候选阈值、止损止盈或仓位参数",
    "根据回测结果选择、晋级或淘汰策略",
    "修改回测收益、风险指标或晋级门槛",
    "生成最终推荐分数、买卖决定或真实交易指令",
    "连接券商或提交任何真实订单",
]

DETERMINISTIC_ENGINE = [
    "数据质量校验与未来数据隔离",
    "因子计算、评分、排序与候选过滤",
    "T+1和可成交约束纸面模拟",
    "回测、成本、风险与组合指标计算",
    "推荐与操作区间指令契约输出",
    "按预注册硬门槛给出通过或拒绝结果",
]


def authority_policy() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "principle": "AI只处理数据；系统只做推荐与纸面校验，不连接券商、不自动下单",
        "product_mode": "recommendation_only",
        "broker_integration": False,
        "human_decisions": HUMAN_DECISIONS,
        "ai": {
            "scope": "data_processing_only",
            "allowed": AI_ALLOWED,
            "forbidden": AI_FORBIDDEN,
        },
        "deterministic_python": {
            "scope": "calculation_scoring_recommendation_only",
            "responsibilities": DETERMINISTIC_ENGINE,
            "ai_output_may_enter_score_directly": False,
            "may_submit_broker_orders": False,
        },
    }
