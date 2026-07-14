# AI 量化系统 · 代码与模块优化需求文档

> 日期：2026-07-14  
> 基线：MVP / v2 首版主线已全量完成（数据 → 因子 → 回测 → 预测 → 候选 → 决策 → 模拟交易 → 复盘 → Agent → 控制台 → 监控 → 注册表）。  
> 本文替代已归档的 MVP 建设清单与 `Quantification-Roadmap-v2.md`，专注三件事：**代码优化、功能点优化、当前功能模块拆分**。  
> 能力扩展（全市场股票池、真实 LLM、外部通知等）仍见 `Quantification-Roadmap-v3.md`；本文与 v3 并行，优先保证工程可维护性。  
> 当前进展：S-01 / O-01、S-02 / O-02、S-03、S-04、S-05 已完成首轮落地；后续推进 S-06 决策域边界。

---

## 1. 目标与原则

### 1.1 目标

把「功能已齐、结构偏胖」的代码库，整理成边界清晰、可单测、可替换、可并行开发的模块化系统。

### 1.2 原则

| 原则 | 说明 |
|------|------|
| 不破坏闭环 | 优化期间 `./run.sh all` 仍可跑通；产物路径与报告入口保持兼容 |
| 先拆后扩 | 模块边界清晰后再做 V3-03 全市场扩展，避免胖模块继续膨胀 |
| 契约优先 | 跨模块只通过 `contracts/` 与稳定 JSON Schema 交互，禁止互相直读内部实现 |
| 一处真相 | 同一业务逻辑只保留一个实现；报表脚本不重复业务计算 |
| 可回滚 | 每次拆分保留旧入口适配层至少一轮，测试通过后再删兼容层 |

### 1.3 MVP 归档结论

| 项 | 结论 |
|----|------|
| MVP 闭环（数据→因子→回测→报告） | ✅ 已全量完成，建设清单归档 |
| v2 首版主线（推荐/复盘/Agent/控制台/监控/注册表） | ✅ 已全量完成，`Quantification-Roadmap-v2.md` 已移除 |
| `./run.sh mvp` | 保留为 `all` 的兼容别名，不再作为「待建设」目标 |
| 本文角色 | 工程优化与模块拆分的唯一执行文档 |

---

## 2. 当前模块现状（拆分前）

### 2.1 业务域一览

```text
采集域     data_source / pipeline / storage / tasks(daily|stock|intraday|enhance|sentiment|inspect|backfill)
研究域     factors / strategy / backtest / prediction / replay / evaluation
决策域     selector / decision / impact / attribution / recommendation / portfolio / risk / trading
智能域     agent / contracts
展示域     script/gen_* / reports / console
运维域     monitoring / registry / scheduler / planning / utils
```

### 2.2 已知结构问题

| 问题 | 表现 | 影响 |
|------|------|------|
| 入口过重 | ✅ 已首轮拆分：`main.py` 38 行，命令注册、分发、流水线、报表触发分离 | 后续只需在新增命令时保持分层 |
| 数据源上帝类 | ✅ 已首轮拆分：`akshare_api.py` 68 行门面，spot / quote / daily / market_meta / snapshot 独立 | 后续只需继续补 Provider 粒度测试 |
| 增强接口臃肿 | ✅ 已首轮拆分：`enhance_api.py` 51 行门面，valuation / corporate / fund_flow / bundle 独立 | 后续继续补真实源集成测试 |
| 报表脚本分散 | S-04 已新增 `presentation/report_base.py` / `i18n.py`，并迁移 console / selector / stock / market / index 核心脚本 | 后续逐步迁移其余小型 `gen_*` 脚本 |
| 任务层薄但多 | S-05 首轮已新增 `tasks/runtime.py`，迁移 sentiment / enhance / stock / intraday 的 watchlist、并发与索引写入模板 | 后续逐步扩展到更多 job |
| 配置碎片化 | `config/*` + `mvp_config` 命名过时 | 新人难找「系统默认参数」 |
| 契约未反向约束 | `contracts/` 有快照，但各 job 仍自由拼 dict | 字段漂移、Agent/Web 难消费 |

### 2.3 目标分层（拆分后）

```text
quant_system/
  apps/                 # CLI / 调度入口（从 main.py 拆出）
  domain/
    market/             # 行情、指数、行业、分钟线
    research/           # 因子、策略、回测、预测、推演
    decision/           # 候选、决策、推荐、组合、风控、模拟交易
    intelligence/       # Agent、契约适配
  infra/
    data_source/        # 东财/新浪/同花顺/雪球 Provider
    storage/            # JSON/MySQL/Redis
    monitoring/         # 任务日志、注册表、告警
  presentation/         # 报表生成（逐步收拢 script/）
  shared/               # config、utils、models、contracts
```

> 落地时允许渐进迁移：先在现有目录内拆文件，再整体挪包；不要求一次大搬家。

---

## 3. 代码优化需求

| 编号 | 项 | 优先级 | 验收标准 |
|------|----|--------|----------|
| O-01 | 拆分 `main.py`：命令解析 / 流水线编排 / 报表触发分离 | P0 | ✅ `main.py` 38 行；`cli/commands/pipeline/reports` 已拆；单测覆盖 `mvp/all` 分发 |
| O-02 | 拆分 `AkShareAPI`：spot / daily / index / industry 独立 Provider | P0 | ✅ `akshare_api.py` 68 行门面；Provider 单文件 ≤250 行；降级测试全绿 |
| O-03 | 统一并发与超时：`concurrent_fetch` + 请求 timeout 配置化 | P0 | 所有外网调用有超时；失败只打一次中文日志；会话级源关闭可测 |
| O-04 | 统一错误与降级标签：`i18n_labels` 覆盖所有报告 limitations | P1 | 报告页无裸英文枚举；新增 limitation 必须先登记中文 |
| O-05 | 消除重复业务逻辑：报表脚本只读 JSON，不重算因子/信号 | P1 | 首轮：公共读写与 i18n 入口已建立；后续迁移大脚本并检查 pandas 重算 |
| O-06 | 配置收敛：`mvp_config` 更名为 `system_defaults`，环境变量表文档化 | P1 | README 有完整 env 表；旧名保留兼容 import 一轮 |
| O-07 | 测试分层：unit（纯函数）/ integration（本地 JSON）/ network（可选 skip） | P1 | `pytest -m "not network"` 默认 CI 可离线全绿 |
| O-08 | 类型与公共模型：关键 payload 用 TypedDict 或 dataclass | P2 | prediction/selector/decision 输出有类型；mypy 或 pyright 可对 domain 跑通 |

---

## 4. 功能点优化需求

| 编号 | 模块 | 优化点 | 优先级 | 验收标准 |
|------|------|--------|--------|----------|
| F-01 | 行情采集 | 东财长期不可用时默认优先新浪/雪球/腾讯，减少无效探测 | P0 | 代理环境下首只失败后不再逐只打东财；日志仅一条关闭提示 |
| F-02 | 盘中采集 | 分钟线失败快速降级为现价看板，不阻塞 `all` | P0 | 分钟线超时 ≤12s；无分钟线仍写出 live JSON |
| F-03 | enhance | 字段级并发 + 源级禁用；两融只查对应交易所 | P0 | 4 只 watchlist enhance 在可接受网络下显著快于串行 |
| F-04 | selector/decision | 校准与价位触发说明写入报告中文区 | P1 | 报告可见阈值来源与买卖观察价，无英文内部字段 |
| F-05 | review/replay | pending 样本与校准闭环说明统一 | P1 | 样本不足时报告明确「中性处理」原因 |
| F-06 | recommendation | 缺额原因、周期权重可配置且可解释 | P1 | 配置变更后报告展示权重版本 |
| F-07 | monitoring | 任务失败与注册表降级在控制台首页可见 | P1 | console 一屏看到最近失败任务与降级产物 |
| F-08 | Agent | Provider 输出强制走 Policy Guard；审计字段完整 | P2 | 无密钥时降级路径有审计 JSON |

---

## 5. 功能模块拆分需求

> **详细拆分清单（目标文件 / 行数 / 验收勾选）见 [`Quantification-Module-Split.md`](Quantification-Module-Split.md)。**  
> 本节只保留优先级摘要；落地前先按拆分清单评审，再改代码。

### 5.1 拆分优先级（唯一执行顺序）

| 顺序 | 编号 | 拆分任务 | 输入 | 输出 | 验收 |
|------|------|----------|------|------|------|
| 1 | S-01 | CLI / 流水线拆分 | `main.py` | ✅ `apps/cli.py` + `apps/commands.py` + `apps/pipeline.py` + `apps/reports.py` | 命令行为不变；测试覆盖 mvp/all 分发 |
| 2 | S-02 | 行情 Provider 拆分 | `akshare_api.py` | ✅ `data_source/providers/spot.py` `spot_quote.py` `daily.py` `market_meta.py` `snapshot.py` | 原 `AkShareAPI` 变为门面；测试全绿 |
| 3 | S-03 | 增强 Provider 拆分 | `enhance_api.py` | ✅ valuation / corporate / fund_flow / bundle 子模块 | enhance_job 接口不变 |
| 4 | S-04 | 报表公共层 | `script/gen_*.py` | ✅ 已新增 `presentation/report_base.py` + `presentation/i18n.py` | console / selector / stock / market / index 已接入；其余脚本逐步迁移 |
| 5 | S-05 | 任务编排公共层 | `tasks/*_job.py` | ✅ `tasks/runtime.py` 已覆盖 watchlist 解析、并发 map、成功项过滤、index 写入钩子 | `sentiment_job` 样板 ≤80 行；intraday 已迁移 |
| 6 | S-06 | 决策域边界 | selector/decision/recommendation/portfolio | 明确输入契约，禁止互相 import 内部 builder | contracts 快照字段与 job 输出一致 |
| 7 | S-07 | 包目录渐进迁移 | 现有顶层包 | `domain/` `infra/` `apps/`（可选） | 旧 import 路径保留 `__init__` 转发一轮 |

### 5.2 模块边界规则（拆分后强制）

| 模块 | 允许依赖 | 禁止依赖 |
|------|----------|----------|
| data_source | config, utils, models | factors, backtest, decision, agent |
| factors | pipeline 输出, storage 读 | trading, agent, script |
| backtest / prediction | factors, strategy, storage | decision, trading |
| selector / decision / recommendation | contracts + 上游 JSON | 直接调 akshare |
| trading / portfolio | risk + decision JSON | data_source 直连 |
| agent | contracts / EvidencePackage | 交易下单接口 |
| script / presentation | 只读 assets/data | 业务重算 |
| monitoring / registry | storage, task_runs | 修改业务结果 |

### 5.3 单文件体量门槛

| 类型 | 建议上限 | 超限动作 |
|------|----------|----------|
| 业务模块 `.py` | 300 行 | 按职责拆文件 |
| Job / 报表脚本 | 200 行 | 抽公共 helper |
| 测试文件 | 按场景拆分 | 单测文件对应一个模块 |

---

## 6. 当前唯一下一步

| 顺序 | 只做这一项直到验收 | 说明 |
|------|--------------------|------|
| 0 | ✅ 拆分清单评审（`Quantification-Module-Split.md`） | 已确认目标文件与顺序 |
| 1 | ✅ S-01 + O-01：拆分 CLI / 流水线 | 已从 `main.py` 抽出命令解析、分发、流水线和报表触发 |
| 2 | ✅ S-02 + O-02：行情 Provider 拆分 | 已解决 `AkShareAPI` 上帝类问题，保留原 import 门面 |
| 3 | ✅ S-04：报表公共层主要脚本迁移 | 已收拢 `gen_stock_report.py`、`gen_report.py`、`gen_console_report.py`、`gen_selector_report.py`、`report_index_utils.py` 的公共读写 / CSS / JSON 注入 |
| 4 | ✅ S-03：增强 Provider 拆分 | 已拆分 `enhance_api.py` 的估值、公司行为、资金与 bundle |
| 5 | ✅ S-05：任务编排公共层首轮 | 已迁移 `sentiment_job`、`enhance_job`、`stock_job`、`intraday_job`，并补充 index 写入钩子 |
| 6 | **S-06：决策域边界** | 当前唯一下一步，检查 selector / decision / recommendation / portfolio 等跨包依赖 |
| 7 | 回到 `Quantification-Roadmap-v3.md` 的 V3-03 | 模块边界清晰后再扩股票池 |

---

## 7. 非目标（本文不做）

- 自动实盘下单、券商交易接口实现（仍属 v3 / 实盘辅助）。
- 全市场重型拉取与横截面因子检验（V3-03 / V3-04）。
- 真实外部 LLM 接入（V3-05）。
- 重写前端为 SPA（控制台保持静态 HTML，仅做公共层收拢）。

---

## 8. 验收总口径

- `./run.sh all`（或 `mvp` 别名）在无代理或东财关闭环境下可完成主链路。
- `pytest -q` 全绿；新增拆分均有对应单测。
- 报告页无未翻译的英文状态枚举。
- `main.py` / `akshare_api.py` 体量下降到门槛内，或已有明确门面 + 子模块。
- 文档：本文为工程优化唯一入口；`Quantification.md` 仅保留能力说明与归档状态。

---

## 9. 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.8 | 2026-07-14 | 完成 S-05 首轮收尾：`intraday_job.py` 接入 `tasks/runtime.py`，runtime 增加 index 写入钩子，sentiment / enhance / stock / intraday 均复用公共 watchlist、并发和成功项过滤模板；当前唯一下一步推进为 S-06 决策域边界 |
| v1.7 | 2026-07-14 | 完成 S-05 任务 runtime 首轮：新增 `tasks/runtime.py`，统一 codes/watchlist 解析、科创参考过滤、并发 map、成功项过滤和空列表日志；迁移 `sentiment_job`、`enhance_job`、`stock_job` 的重复编排；新增 runtime 单测；当前唯一下一步继续迁移 `intraday_job` |
| v1.6 | 2026-07-14 | 完成 S-03 增强 Provider 首轮拆分：`enhance_api.py` 降为 51 行门面，新增 `data_source/enhance/runtime.py`、`valuation.py`、`corporate.py`、`fund_flow.py`、`bundle.py`；`enhance_job` 调用方式不变；当前唯一下一步推进为 S-05 任务编排公共层 |
| v1.5 | 2026-07-14 | 完成 S-04 主要大脚本迁移：`gen_stock_report.py`、`gen_report.py`、`report_index_utils.py` 接入 `presentation/report_base.py`，统一 JSON/文本读写、HTML 写入、公共 CSS 与安全 JSON 注入；报表公共层测试增至 7 项；当前唯一下一步推进为 S-03 增强 Provider 拆分 |
| v1.4 | 2026-07-14 | 完成 S-04 报表公共层首轮：新增 `presentation/report_base.py` 与 `presentation/i18n.py`，收敛 JSON 读写、HTML 写入、公共 CSS、内嵌 JSON 安全转义；迁移 `gen_console_report.py` 与 `gen_selector_report.py` 作为样板；当前唯一下一步继续迁移 stock / market / index 大脚本 |
| v1.3 | 2026-07-13 | 完成 S-02 / O-02 首轮代码拆分：`AkShareAPI` 降为 68 行门面，新增 `data_source/providers/spot.py`、`spot_quote.py`、`daily.py`、`market_meta.py`、`snapshot.py`；Provider 单文件均 ≤250 行；当前唯一下一步推进为 S-04 报表公共层 |
| v1.2 | 2026-07-13 | 完成 S-01 / O-01 首轮代码拆分：新增 `apps/cli.py`、`apps/commands.py`、`apps/pipeline.py`、`apps/reports.py`；`main.py` 降至 38 行；新增 CLI 分发单测；当前唯一下一步推进为 S-02 行情 Provider 拆分 |
| v1.1 | 2026-07-10 | 拆分项独立成 `Quantification-Module-Split.md`；本阶段只整理文档不改代码；唯一下一步增加「清单评审」 |
| v1.0 | 2026-07-10 | 确认 MVP/v2 已全量完成并归档；移除 `Quantification-Roadmap-v2.md` 与 `ExcellentQuantSystemRequirements.md`；新增代码优化、功能点优化、模块拆分需求与唯一执行顺序 |
