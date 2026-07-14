# AI 量化系统 · 功能模块拆分清单

> 日期：2026-07-14  
> 状态：**S-01 / S-02 / S-03 / S-04 / S-05 已首轮落地，下一步 S-06 决策域边界**  
> 关联：`Quantification-Optimization.md`（S-01～S-07）  
> 目的：把「当前要拆什么、拆到哪、依赖谁、验收什么」整理成可执行清单，落地前先评审。

---

## 1. 拆分原则（摘要）

| 原则 | 说明 |
|------|------|
| 行为不变 | 拆分后 `./run.sh all` / 各子命令语义不变 |
| 先拆文件，再挪包 | 第一轮在现有目录内拆；`domain/` `apps/` 整包迁移放最后 |
| 门面保留 | 旧入口（如 `AkShareAPI`、`main.py`）保留薄封装，避免一次改全仓库 import |
| 契约边界 | 跨域只读 JSON / `contracts/`，禁止互相 import 内部 builder |
| 体量门槛 | 业务文件建议 ≤300 行；Job/报表建议 ≤200 行 |

---

## 2. 当前体量快照（2026-07-10）

### 2.1 优先拆分对象（超标）

| 文件 | 行数 | 问题 | 归属拆分项 |
|------|------|------|------------|
| `quant_system/main.py` | 38 | ✅ 已变为薄入口；原职责拆到 `apps/cli.py` / `apps/commands.py` / `apps/pipeline.py` / `apps/reports.py` | S-01 |
| `quant_system/data_source/akshare_api.py` | 68 | ✅ 已变为门面；职责拆到 `providers/spot.py` / `spot_quote.py` / `daily.py` / `market_meta.py` / `snapshot.py` | S-02 |
| `quant_system/data_source/enhance_api.py` | 51 | ✅ 已变为门面；职责拆到 `data_source/enhance/*` | S-03 |
| `script/gen_stock_report.py` | 544 | ✅ 已接入公共读写 / CSS / JSON 注入；模板仍大，后续可继续拆分区块 | S-04 |
| `script/gen_report.py` | 321 | ✅ 已接入公共读写 / CSS / JSON 注入；索引逻辑保留 | S-04 |
| `script/gen_console_report.py` | 303 | ✅ 已接入公共读写 / CSS / JSON 注入 | S-04 |
| `script/report_index_utils.py` | 291 | ✅ 已接入公共路径、JSON 读取与 HTML 写入 | S-04 |
| `quant_system/tasks/intraday_job.py` | 197 | ✅ 已接入 `tasks/runtime.py`；分钟线安全拉取仍保留在任务内 | S-05 |

### 2.2 暂不强制拆（体量可接受）

| 区域 | 说明 |
|------|------|
| 多数 `tasks/*_job.py`（20～170 行） | 先抽公共 runtime，再视重复度拆 |
| `eastmoney.py` / `tonghuashun.py` / `xueqiu.py` / `minute_api.py` | 已相对独立，S-02 时作为 Provider 复用 |
| `factors/` `backtest/` `prediction/` 等业务包 | 边界基本清晰，S-06 只约束跨包依赖 |

---

## 3. 拆分项明细

### S-01 CLI / 流水线拆分（P0 · 已完成首轮）

**现状**：`main.py` 已降至 38 行，仅负责项目路径、解析入口、任务运行记录和调用分发；命令参数、命令分发、流水线和报表触发已经拆分。

| 目标文件 | 迁出内容 | 说明 |
|----------|----------|------|
| `quant_system/apps/cli.py` | `build_parser()` | ✅ 仅命令与参数定义 |
| `quant_system/apps/commands.py` | `_execute(args)` 各命令分支 | ✅ 单命令调度，调用 tasks + reports |
| `quant_system/apps/pipeline.py` | `run_mvp_pipeline` / `all` 编排顺序 | ✅ 全链路步骤表，可继续增强顺序单测 |
| `quant_system/apps/reports.py` | 全部 `generate_*` / `sync_report_index_hubs` | ✅ 报表触发集中 |
| `quant_system/main.py` | 保留：`ROOT`、path、`main()`、TaskRunRecorder | ✅ 38 行入口 |

**流水线步骤（`all` / `mvp` 应对齐，文档化后实现）**

```text
1  inspect（可选）
2  ensure_watchlist_history
3  market → stock
4  sentiment（可选）
5  enhance（all 可选；mvp 默认执行）
6  factor → intraday
7  backtest → predict（可选）
8  impact → selector → decision → simtrade → portfolio → review → attribution
9  reports / factor / enhance / live / agent / console / monitor
10 sync_report_index_hubs
```

**验收**

- [x] `main.py` ≤100 行（或仅入口）
- [x] `pytest` 覆盖：`mvp` 别名与 `all` skip 参数分发
- [ ] 增强 `pipeline` 步骤顺序单测（mock tasks，后续补强）
- [x] `mvp` 与 `all` 行为与拆分前一致（skip 参数仍生效）

**依赖**：无前置代码拆分依赖。

---

### S-02 行情 Provider 拆分（P0 · 已完成首轮）

**现状**：`akshare_api.py` 已降至 68 行，仅保留初始化、AkShare 懒加载、东财探测兼容和 Provider 组合。

| 目标文件 | 职责 | 从现有迁出 |
|----------|------|------------|
| `data_source/providers/spot.py` | 全市场现价、批量快照、cache fallback | ✅ 已完成 |
| `data_source/providers/spot_quote.py` | 逐只盘口、雪球、腾讯/新浪日 K 降级 | ✅ 已完成 |
| `data_source/providers/daily.py` | 日 K 多源（东财/新浪/腾讯） | ✅ 已完成 |
| `data_source/providers/market_meta.py` | 指数、行业、资金流 | ✅ 已完成 |
| `data_source/providers/snapshot.py` | 大盘快照组装 | ✅ 已完成 |
| `data_source/akshare_api.py` | 门面：组合上述 Provider | ✅ 对外 API 签名不变 |

**已有可复用**

- `eastmoney.py`、`xueqiu.py`、`tonghuashun.py`、`minute_api.py`、`source_guard.py`

**验收**

- [x] 单文件 ≤250 行（门面除外可更薄）
- [x] `test_spot_fallback` / `test_market_degraded` / `test_source_guard` 全绿
- [x] 外部仍 `from quant_system.data_source.akshare_api import AkShareAPI`

**依赖**：建议 S-01 完成后做，避免入口与数据源同时大改。

---

### S-03 增强 Provider 拆分（P1 · 已完成首轮）

**现状**：`enhance_api.py` 已降至 51 行，仅保留初始化、AkShare 懒加载和 Provider 组合。

| 目标文件 | 职责 |
|----------|------|
| `data_source/enhance/runtime.py` | ✅ 源级禁用、失败去重、重试与中文化错误 |
| `data_source/enhance/valuation.py` | ✅ PE/PB/市值（东财/百度/同花顺） |
| `data_source/enhance/corporate.py` | ✅ 分红、解禁、业绩预告 |
| `data_source/enhance/fund_flow.py` | ✅ 北向、两融、大盘资金 |
| `data_source/enhance/bundle.py` | ✅ `fetch_stock_bundle` 并发组装 |
| `data_source/enhance_api.py` | ✅ 门面，供 `enhance_job` 调用 |

**验收**

- [x] `enhance_job` 无需改调用方式（或仅改 import）
- [x] `test_enhance` / bundle 并发测试全绿
- [x] 源级禁用（东财/同花顺）逻辑仍集中在一处

**依赖**：S-02 的 source_guard 模式可复用。

---

### S-04 报表公共层（P1 · 主要脚本已完成）

**现状**：`script/gen_*.py` 约 24 个，合计 ~4200 行；已建立公共层，并迁移核心大脚本。

| 目标 | 内容 |
|------|------|
| `quant_system/presentation/report_base.py` | ✅ 读 JSON、写 HTML、公共 CSS 引用、安全 JSON script |
| `quant_system/presentation/i18n.py` | ✅ 转发 `utils/i18n_labels.py`，作为报表统一入口 |
| `script/gen_console_report.py` | ✅ 已接入 base |
| `script/gen_selector_report.py` | ✅ 已接入 base + i18n |
| `script/gen_stock_report.py` | ✅ 已接入 base |
| `script/gen_report.py` | ✅ 已接入 base |
| `script/report_index_utils.py` | ✅ 已接入 base |
| `script/gen_*.py` | 继续变薄：只组业务表格行，调用 base |

**优先收拢脚本**

1. `gen_stock_report.py`（556）
2. `gen_report.py`（323）
3. `gen_console_report.py`（309）
4. `report_index_utils.py`（289）
5. 其余 gen_* 按改动频率逐步迁

**验收**

- [x] 新建报告必须走 base + i18n（首轮入口已建立）
- [ ] 报告页无裸英文 limitation/verdict（已有映射处统一调用）
- [ ] 脚本内无 pandas 重算因子/信号
- [x] 继续迁移 `gen_stock_report.py`、`gen_report.py`、`report_index_utils.py`
- [ ] 后续逐步迁移其余小型 `gen_*` 脚本

**依赖**：可与 S-02 并行（展示层独立）。

---

### S-05 任务编排公共层（P1 · 首轮已完成）

**现状**：`tasks/` 约 25 个 job，模式重复：load watchlist → 处理 → save index → log。首轮已迁移 sentiment / enhance / stock / intraday。

| 目标 | 内容 |
|------|------|
| `tasks/runtime.py` | ✅ `resolve_stock_items`、`run_for_watchlist`、并发 map、成功项过滤、index 写入钩子 |
| 各 `*_job.py` | 首轮：`sentiment_job` ≤80 行，`enhance_job` / `stock_job` / `intraday_job` 已复用 runtime |

**优先改造 job（重复度高 / 已并发）**

- `stock_job` / `enhance_job` / `sentiment_job` / `intraday_job`

**验收**

- [x] 新 job 样板代码 ≤80 行（`sentiment_job.py` 66 行）
- [x] 现有 job 行为不变；相关单测全绿
- [x] 继续迁移 `intraday_job.py`
- [x] 增加 index 写入钩子，进一步减少 job 尾部样板
- [ ] 后续逐步迁移其它相同模式 job

**依赖**：S-01 的 pipeline 可调用 runtime，但不强绑。

---

### S-06 决策域边界（P1）

**包**：`selector` / `decision` / `recommendation` / `portfolio` / `impact` / `attribution` / `trading` / `risk`

| 规则 | 说明 |
|------|------|
| 允许 | 读上游 JSON；读 `contracts/`；读 `risk` 规则 |
| 禁止 | `selector` import `decision.builder` 内部；decision 直调 akshare |
| 输出 | 一律可被 `contracts` 适配为标准对象 |

**验收**

- [ ] 依赖方向检查（文档或简单 import lint）
- [ ] `framework` 快照字段与各 job 输出一致

**依赖**：S-01～S-03 非必须，可穿插做「禁止清单」评审。

---

### S-07 包目录渐进迁移（P2 · 最后）

仅在 S-01～S-06 稳定后执行。

```text
quant_system/
  apps/           # cli / pipeline / commands / reports
  domain/
    market/       # 可选：从 data_source 门面再上提
    research/     # factors strategy backtest prediction replay evaluation
    decision/     # selector decision recommendation portfolio trading risk impact attribution
    intelligence/ # agent contracts
  infra/
    data_source/
    storage/
    monitoring/
    registry/
  presentation/   # 报表
  shared/         # config utils models
```

**验收**

- [ ] 旧 import 路径 `__init__.py` 转发至少保留一轮
- [ ] CI / 本地 pytest 全绿后再删转发

---

## 4. 建议执行顺序（只文档阶段确认）

| 顺序 | 项 | 是否改代码 | 备注 |
|------|----|------------|------|
| 0 | ✅ 本文评审通过 | 否 | 已完成 |
| 1 | ✅ S-01 CLI / 流水线 | 是 | 首轮已完成；保留 pipeline 顺序单测补强项 |
| 2 | ✅ S-02 行情 Provider | 是 | 已完成首轮 |
| 3 | ✅ S-04 报表公共层主要脚本迁移 | 是 | 已完成 stock / market / index |
| 4 | ✅ S-03 增强 Provider | 是 | 已完成首轮 |
| 5 | ✅ S-05 任务 runtime 首轮 | 是 | 已完成 sentiment / enhance / stock / intraday |
| 6 | **S-06 决策域边界** | 是（偏约束） | 当前唯一下一步 |
| 6 | S-06 决策域边界 | 是（偏约束） | |
| 7 | S-07 整包迁移 | 是 | 可选 |

能力扩展（全市场股票池等）仍见 `Quantification-Roadmap-v3.md`，建议在 S-01～S-02 完成后再扩。

---

## 5. 非拆分项（明确不做）

- 不借拆分之机重写策略/回测算法。
- 不改为 SPA 前端。
- 不在本清单内实现券商交易接口。
- 不删除 `./run.sh mvp` 别名（仅文档归档语义）。

---

## 6. 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.7 | 2026-07-14 | 完成 S-05 首轮收尾：迁移 intraday，runtime 增加 index 写入钩子，四个优先 job 均接入公共任务编排；下一步推进 S-06 决策域边界 |
| v1.6 | 2026-07-14 | 完成 S-05 首轮：新增 `tasks/runtime.py`，迁移 sentiment / enhance / stock 的 watchlist 解析与并发执行；新增 runtime 单测；下一步继续迁移 intraday |
| v1.5 | 2026-07-14 | 完成 S-03 增强 Provider 首轮拆分：`enhance_api.py` 降至 51 行门面，新增 runtime / valuation / corporate / fund_flow / bundle；下一步推进 S-05 任务 runtime |
| v1.4 | 2026-07-14 | 完成 S-04 主要大脚本迁移：stock / market / index 工具接入 report_base；公共层测试扩展；下一步推进 S-03 增强 Provider 拆分 |
| v1.3 | 2026-07-14 | 完成 S-04 首轮公共层：新增 report_base / presentation i18n，迁移 console 与 selector 报告，补充公共层测试；下一步继续迁移 stock / market / index 大脚本 |
| v1.2 | 2026-07-13 | 完成 S-02 首轮代码拆分：`AkShareAPI` 降至 68 行门面，新增 spot / spot_quote / daily / market_meta / snapshot Provider；更新验收状态与下一步为 S-04 |
| v1.1 | 2026-07-13 | 完成 S-01 首轮代码拆分：入口降至 38 行，新增 `apps/cli.py`、`apps/commands.py`、`apps/pipeline.py`、`apps/reports.py`；更新验收状态与下一步为 S-02 |
| v1.0 | 2026-07-10 | 按仓库实测行数整理 S-01～S-07 拆分清单；明确目标文件、验收与执行顺序；本阶段不改代码 |
