"""策略诊断 Agent（P4-1）。"""

from __future__ import annotations

from typing import Any

from quant_system.agent.context import StockContext
from quant_system.config.agent_config import HIGH_DRAWDOWN, WEAK_SHARPE, WEAK_WIN_RATE


def diagnose_strategy(ctx: StockContext, strategy: str = "ma_cross") -> dict[str, Any]:
    bt = ctx.backtest(strategy)
    if not bt:
        return {
            "available": False,
            "strategy": strategy,
            "verdict": "unknown",
            "findings": ["缺少回测结果，请先运行 backtest"],
            "suggestions": ["./run.sh backtest --allow-warn"],
        }

    m = bt.get("metrics") or {}
    attr = bt.get("attribution") or {}
    rolling = bt.get("rolling") or {}
    strat = bt.get("strategy", strategy)

    findings: list[str] = []
    suggestions: list[str] = []
    win_rate = m.get("win_rate_pct")
    sharpe = m.get("sharpe_ratio")
    mdd = m.get("max_drawdown_pct")

    if win_rate is not None and win_rate < WEAK_WIN_RATE:
        findings.append(f"胜率偏低（{win_rate}%）")
        suggestions.append("考虑提高买入阈值或叠加趋势过滤")
    if sharpe is not None and sharpe < WEAK_SHARPE:
        findings.append(f"夏普偏低（{sharpe}）")
        suggestions.append("收益波动比不佳，宜降低仓位或缩短持仓周期")
    if mdd is not None and mdd <= HIGH_DRAWDOWN:
        findings.append(f"历史最大回撤较大（{mdd}%）")
        suggestions.append("设置账户级回撤熔断，避免单边行情重仓")

    worst = (attr.get("worst_trade") or {})
    if worst.get("pnl") is not None and float(worst["pnl"]) < -5000:
        findings.append(f"单笔最大亏损 {worst['pnl']}（{worst.get('reason', '')}）")

    if rolling.get("window_count"):
        oos = rolling.get("oos_avg_return_pct")
        ratio = rolling.get("oos_positive_ratio")
        findings.append(f"滚动 OOS {rolling['window_count']} 窗，均收益 {oos}%，正收益占比 {ratio}")
        if ratio is not None and ratio < 0.5:
            suggestions.append("样本外稳定性不足，不宜放大实盘仓位")

    if not findings:
        findings.append("回测指标处于可接受区间")

    weak_signals = sum([
        1 if win_rate is not None and win_rate < WEAK_WIN_RATE else 0,
        1 if sharpe is not None and sharpe < WEAK_SHARPE else 0,
        1 if mdd is not None and mdd <= HIGH_DRAWDOWN else 0,
    ])
    if weak_signals >= 2:
        verdict = "weak"
    elif weak_signals == 0 and (win_rate or 0) >= 45:
        verdict = "ok"
    else:
        verdict = "mixed"

    return {
        "available": True,
        "strategy": strat,
        "verdict": verdict,
        "findings": findings,
        "suggestions": suggestions or ["维持现有参数，持续滚动验证"],
        "metrics": {
            "annual_return_pct": m.get("annual_return_pct"),
            "max_drawdown_pct": mdd,
            "sharpe_ratio": sharpe,
            "win_rate_pct": win_rate,
            "closed_trades": m.get("closed_trades"),
        },
        "attribution_top": (attr.get("by_reason") or [])[:3],
        "rolling_summary": {
            "window_count": rolling.get("window_count"),
            "oos_avg_return_pct": rolling.get("oos_avg_return_pct"),
            "oos_positive_ratio": rolling.get("oos_positive_ratio"),
        } if rolling.get("window_count") else None,
    }
