"""CLI parser definition."""

from __future__ import annotations

import argparse

from quant_system.apps.commands import execute_command


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="A股量化数据采集系统")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("scheduler", help="启动定时调度器")

    market = sub.add_parser("market", help="采集大盘行情")
    market.add_argument("--mock", action="store_true", help="使用已有 JSON 数据")

    stock = sub.add_parser("stock", help="采集自选股分析")
    stock.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    live = sub.add_parser("live", help="盘中实时采集（分钟线+实时价）")
    live.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    live.add_argument("--loop", action="store_true", help="循环采集直到 Ctrl+C")
    live.add_argument("--interval", type=int, default=60, help="循环间隔秒数")

    factor = sub.add_parser("factor", help="计算自选股技术因子")
    factor.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    factor.add_argument("--force", action="store_true", help="忽略质量门禁")
    sub.add_parser("factor-eval", help="因子有效性评估（相关性、分层收益、漂移）")

    inspect = sub.add_parser("inspect", help="K 线质量巡检")
    inspect.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    inspect.add_argument("--fix", action="store_true", help="发现问题时自动 backfill")
    inspect.add_argument("--lookback", type=int, default=60, help="缺口检测窗口（自然日）")

    backfill = sub.add_parser("backfill", help="补录历史 K 线")
    backfill.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    backfill.add_argument("--days", type=int, default=250)
    backfill.add_argument("--no-refresh", action="store_true", help="仅写 backfill/ 归档，不刷新 stocks")

    run = sub.add_parser("run", help="执行单个调度任务")
    run.add_argument("job", choices=[
        "daily_market", "daily_stock", "intraday_snapshot",
        "data_inspect", "factor_compute", "backfill_weekly",
    ])

    all_cmd = sub.add_parser("all", help="inspect → market → stock → 回测 → 预测 → 报表")
    all_cmd.add_argument("--skip-inspect", action="store_true", help="跳过质量巡检")
    all_cmd.add_argument("--skip-backtest", action="store_true", help="跳过回测")
    all_cmd.add_argument("--skip-predict", action="store_true", help="跳过走势预测")
    all_cmd.add_argument("--skip-sentiment", action="store_true", help="跳过舆情采集")
    all_cmd.add_argument("--skip-enhance", action="store_true", help="跳过数据增强")
    sub.add_parser("mvp", help="MVP 闭环（同 all，含 750 日补录 + 盘中看板 + 舆情）")

    sent = sub.add_parser("sentiment", help="舆情采集（东财评论 + 雪球热榜）")
    sent.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    enhance = sub.add_parser("enhance", help="数据增强（估值/公司行为/资金/指数）")
    enhance.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    impact = sub.add_parser("impact", help="实际影响数据提取（业绩/估值/解禁/材料价格）")
    impact.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    attribution = sub.add_parser("attribution", help="每日涨跌归因（昨日/今日对比）")
    attribution.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")

    agent = sub.add_parser("agent", help="Agent 分析（选股解释/策略诊断/预测复盘）")
    agent.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    agent.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    agent.add_argument("--provider", default="rule", choices=["rule", "llm"], help="Agent Provider，llm 未配置时自动降级")

    decision = sub.add_parser("decision", help="单股指导性操作建议（高指导性、低实时性）")
    decision.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    decision.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    decision.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    decision.add_argument("--no-agent", action="store_true", help="缺少 Agent 报告时不自动生成")
    decision.add_argument("--no-impact", action="store_true", help="缺少实际影响数据时不自动生成")

    selector = sub.add_parser("selector", help="上涨候选池筛选与排名")
    selector.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    selector.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    selector.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    selector.add_argument("--no-impact", action="store_true", help="缺少实际影响数据时不自动生成")

    sim = sub.add_parser("simtrade", help="模拟交易（P3-1，基于决策/预测虚拟调仓）")
    sim.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    sim.add_argument("--reset", action="store_true", help="重置虚拟账户")
    sim.add_argument("--cash", type=float, default=None, help="重置时使用的初始资金")
    sim.add_argument("--no-predict", action="store_true", help="缺少预测时不自动补跑 predict")
    sim.add_argument("--no-decision", action="store_true", help="缺少决策时不自动生成")

    sub.add_parser("portfolio", help="组合管理与账户级风控")
    sub.add_parser("console", help="统一 Web 控制台")
    sub.add_parser("monitor", help="监控告警与数据血缘")
    sub.add_parser("registry", help="数据产物注册表")
    sub.add_parser("v3-plan", help="v3 稳定化与扩展路线")

    bt = sub.add_parser("backtest", help="单策略日线回测（MA金叉）")
    bt.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    bt.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"], help="策略名称")
    bt.add_argument("--days", type=int, default=750, help="回测 K 线天数（约3年=750）")
    bt.add_argument("--cash", type=float, default=100_000, help="初始资金")
    bt.add_argument("--allow-warn", action="store_true", help="允许质量分 70-89 进入回测")
    bt.add_argument("--no-rolling", action="store_true", help="跳过滚动样本外验证")

    pred = sub.add_parser("predict", help="可验证走势预测（5d 方向/概率/置信度）")
    pred.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    pred.add_argument("--strategy", default="ma_cross", choices=["ma_cross", "multi_factor"])
    pred.add_argument("--horizon", default="5d", choices=["1d", "5d", "20d"])
    pred.add_argument("--days", type=int, default=750)
    pred.add_argument("--no-backtest", action="store_true", help="不自动补跑回测")
    pred.add_argument("--allow-warn", action="store_true")

    replay = sub.add_parser("replay", help="十日前视角滚动推演（无未来函数复盘）")
    replay.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    replay.add_argument("--days", type=int, default=10, help="向前回放的交易日数量")

    review = sub.add_parser("review", help="后验复盘（预测/候选/决策 1/5/20 日收益）")
    review.add_argument("codes", nargs="*", help="股票代码，不传则读 watchlist.json")
    recommend = sub.add_parser("recommend", help="短线、中线、长线股票推荐")
    recommend.add_argument("--limit", type=int, default=5, help="每个周期最多推荐数量")
    sub.add_parser("framework", help="模块化算法框架契约快照")

    return p

