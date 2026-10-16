"""短线 / 长线策略分析契约：目标、样本、晋级关注点分开，禁止混用同一结论。"""

from __future__ import annotations

from typing import Any

# 研究候选 horizon → 产品分析轨
# swing（波段）单独作为中线对照，不并入短线结论，也不替代长线质量轨。
TRACK_SHORT = "short"
TRACK_LONG = "long"
TRACK_SWING = "swing"

SHORT_RESEARCH_HORIZONS = frozenset({"short"})
LONG_RESEARCH_HORIZONS = frozenset({"medium", "long"})
SWING_RESEARCH_HORIZONS = frozenset({"swing"})

TRACK_SPECS: dict[str, dict[str, Any]] = {
    TRACK_SHORT: {
        "label": "短线",
        "holding_days": "1-5个交易日",
        "product_outputs": ["每日筛选推荐", "激进板筛选推荐", "隔夜并行研究", "激进板并行研究"],
        "research_horizons": sorted(SHORT_RESEARCH_HORIZONS),
        "entry_model": "收盘信号 → 次日开盘（T+1）",
        "design_constraints": [
            "反追涨：弱势温和涨幅带，不推荐当日已大幅冲高的票",
            "激进板另轨：偏强市+情绪偏热+更高涨幅带，与温和板并行研究",
            "分时硬确认与量价拆分",
            "组合日限流与容量饥渴一票否决",
        ],
        "success_criteria": [
            "隔夜或 short 候选组合 OOS 收益>0 且命中率达标",
            "激进板并行代理边为正时，才考虑在偏强市启用正式激进推荐",
            "accepted_trades 充足且拒单不超过接受笔数 5 倍",
            "前向影子满窗后人工确认才启用正式推荐",
        ],
        "not_success": [
            "收盘后点名当日大涨股（如远东 +6%）不算短线捕捉成功",
            "信号级赚钱但组合级亏损不算可晋级",
        ],
    },
    TRACK_LONG: {
        "label": "长线",
        "holding_days": "约20-60个交易日及以上",
        "product_outputs": ["长线研究诊断（非正式推荐）", "质量门点时财务"],
        "research_horizons": sorted(LONG_RESEARCH_HORIZONS),
        "entry_model": "基本面准入 + 中线趋势择时 → 次日开盘",
        "design_constraints": [
            "点时财务字段缺失则失败关闭，禁止 AI 补值",
            "质量恶化退出与均线/止损并行",
            "不与短线反追涨门禁混用同一评分",
        ],
        "success_criteria": [
            "fundamental_quality 点时连接可用且质量门有真实信号",
            "medium/long 候选组合路径打赢对应 baseline",
            "回撤与持有期稳定性优于短线洪水策略",
        ],
        "not_success": [
            "用短线涨幅榜解释长线是否有效",
            "财务未 join 时把空信号当成策略失败以外的「可调参」空间",
        ],
    },
    TRACK_SWING: {
        "label": "波段(中线对照)",
        "holding_days": "约8-30个交易日",
        "product_outputs": ["研究锦标赛 swing 诊断"],
        "research_horizons": sorted(SWING_RESEARCH_HORIZONS),
        "entry_model": "趋势/回踩技术信号 → 次日开盘",
        "design_constraints": [
            "与短线分开记账，避免全局 train_score 冠军淹没短线结论",
            "容量规则仍适用，但评估叙事不并入长线质量轨",
        ],
        "success_criteria": [
            "swing 组合 OOS 可交易且过晋级条款",
        ],
        "not_success": [
            "把 swing 全局冠军当成短线或长线已就绪",
        ],
    },
}


def track_for_horizon(horizon: str) -> str:
    value = str(horizon or "")
    if value in SHORT_RESEARCH_HORIZONS:
        return TRACK_SHORT
    if value in LONG_RESEARCH_HORIZONS:
        return TRACK_LONG
    if value in SWING_RESEARCH_HORIZONS:
        return TRACK_SWING
    return TRACK_SWING


def candidates_for_track(candidates: list[dict[str, Any]], track: str) -> list[dict[str, Any]]:
    horizons = {
        TRACK_SHORT: SHORT_RESEARCH_HORIZONS,
        TRACK_LONG: LONG_RESEARCH_HORIZONS,
        TRACK_SWING: SWING_RESEARCH_HORIZONS,
    }.get(track, frozenset())
    return [row for row in candidates if str(row.get("horizon") or "") in horizons]
