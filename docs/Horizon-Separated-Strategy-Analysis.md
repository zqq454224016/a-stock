# 短线 / 长线分轨策略分析

更新时间：2026-10-16

## 为什么要分轨

全局锦标赛用 `train_score` 选一个 `selected_candidate`，当前经常是 **swing 波段**冠军。  
若只用这一条结论，会把「短线推不出远东」「长线质量门没数据」混成同一个故事。

分轨后：

- **短线结论**只来自 `short` 候选 + 隔夜研究 + **激进板并行研究** + 正式推荐/漏检审计

## 四轨归并与分市场状态证据

- 归并：`quant_system/strategy/track_catalog.py` 按持有天数把全部并行策略归入四轨（≤2日超短线 / 3–10日短线 / ≥11日长线 / 防守反转ETF），同形态同轨道归为一族，族内只保留开发段最强成员。
- 防守/反转：`quant_system/strategy/defensive_etf.py`，ETF 日线由 `data_source/etf_history.py` 拉取。场内无反向/杠杆 ETF（1649 只全量扫描），下跌市的“反向”只能是空仓、切换国债/黄金/红利/货币 ETF，或在超跌反转条件成立时买宽基 ETF。
- 超跌反转条件（4 项满足≥3 项，回测前冻结）：ETF 收盘低于 MA20 至少 4%；近 3 日平均上涨家数占比≤35%；全市场成交额≥20 日均额 1.2 倍；ETF 收在当日振幅上半部。
- 证据：`python -m quant_system.tasks.strategy_track_evidence_job [--reuse]` → `assets/data/strategy_tracks/latest.json`。按决策时可知的市场状态分组，只用开发段；t 值按周（持有≥11日按月）聚类，个股 t≥3、ETF t≥2，且开发段前后两半均为正。
- 用法：`current.tracks` 给出当前状态下每条轨道是否有证据；路由的静态启停表应与之取交集，不能只看表。

## 尾盘进、次日出

- 策略：`quant_system/strategy/tail_overnight.py`，5 类形态（强势收盘 / 突破20日高 / 回踩10日线 / 低波上涨 / 放量长下影）× 2 种出场（次日开盘 / 次日收盘），共 10 个预登记组合，参数冻结。
- 口径：T 日收盘集合竞价买入，T+1 卖出；佣金万0.8×2、印花税0.05%、按成交额分档滑点；剔除收盘涨停/一字板、ST、次日停牌；次日开盘跌停按更差价成交。
- 研究：`python -m quant_system.tasks.tail_overnight_iteration_job` → `assets/data/tail_overnight/latest.json`；只用开发段挑选，最近60日只诊断；每日前5只等权组合。
- 尾盘推荐：`python -m quant_system.tasks.tail_overnight_recommendation_job`（调度器 14:48 自动跑）→ `assets/data/tail_overnight/recommendation.json`；加分时检查（价在均价上、尾盘不跳水、未封板）。
- 晋级：回测过线 → 研究候选；前向影子账本 `tail_overnight/shadow/{日期}.json`（只在 14:40–15:00 写一次，不覆盖）满 20 个交易日、30 笔且均收益>0、命中≥50% → 待人工确认；写入 `tail_overnight/approval.json` 才进正式推荐。

激进板并行产物：`assets/data/aggressive_board_iterations/latest.json`  
三流：`aggressive_breakout_hot` / `aggressive_volume_thrust` / `aggressive_rs_continuation`（日线代理，不改正式门禁）。
- **长线结论**只来自 `medium`/`long` 候选 + 质量门就绪度
- **swing** 只作对照，写明「不替代长短线」

## 契约摘要

见 `quant_system/strategy/horizon_tracks.py` 中 `TRACK_SPECS`。

## 如何跑

```bash
.venv/bin/python -m quant_system.tasks.horizon_strategy_analysis_job
```

迭代 worker 在策略锦标赛 / 隔夜 / 推荐更新后会自动刷新 `horizon_analysis/`。

## 读报告时

1. 先看 `comparison.short_verdict` 与 `long_verdict`，不要只看 `source.global_selected_*`
2. 短线空推荐 + 远东未荐 → 查 `tracks.short.formal_recommendation`（反追涨设计）
3. 长线未就绪 → 查 `tracks.long.quality_gate`（点时财务是否 join）
