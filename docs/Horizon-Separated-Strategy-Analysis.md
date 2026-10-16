# 短线 / 长线分轨策略分析

更新时间：2026-10-16

## 为什么要分轨

全局锦标赛用 `train_score` 选一个 `selected_candidate`，当前经常是 **swing 波段**冠军。  
若只用这一条结论，会把「短线推不出远东」「长线质量门没数据」混成同一个故事。

分轨后：

- **短线结论**只来自 `short` 候选 + 隔夜研究 + **激进板并行研究** + 正式推荐/漏检审计

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
