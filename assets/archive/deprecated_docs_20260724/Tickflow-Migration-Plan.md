# tickflow-stock-panel 基座迁移梳理 v1.0

> 日期：2026-07-15  
> 结论：为了更快投入使用，采用 **tickflow-stock-panel 作为产品化基座，a-stock 作为决策增强内核** 的双轨迁移方案。  
> 本文不替代 `Quantification.md`，用于指导后续从当前静态报告系统迁移到可交互工作台。

## 1. 总体判断

| 维度 | 当前 a-stock | tickflow-stock-panel | 迁移判断 |
|------|--------------|----------------------|----------|
| 产品入口 | CLI、静态 HTML 报告、本地 JSON | React 工作台、FastAPI、Dashboard、Screener、Backtest、Monitor | 以 tickflow 为使用入口 |
| 数据底座 | AkShare/东财/雪球等多源 JSON 产物 | TickFlow + Parquet + DuckDB + Polars enriched 表 | 以 tickflow 为主，a-stock 数据能力作为补充 |
| 单股分析 | 十日推演、每日归因、决策建议、仓位场景 | 关键价位、K 线、财务、AI 四维分析 | 合并到 tickflow 个股分析页 |
| 选股能力 | selector 阈值校准、影响事件、推荐周期 | 策略插件、全市场向量化扫描、自定义信号 | selector 迁移为策略/评分插件 |
| 复盘能力 | 昨日/今日涨跌归因、后验复盘、命中率闭环 | 市场复盘、连板梯队、概念轮动 | 每日归因并入 Review/Market Recap |
| 监控能力 | 本地产物监控、任务日志、注册表 | 监控中心、规则、触发记录、通知 | 规则监控使用 tickflow，数据血缘保留增强 |
| 投入速度 | 继续补 UI 成本高 | 已有可用前后端和页面 | 优先迁移核心决策模块 |

## 2. 目标架构

```text
tickflow-stock-panel
  frontend/
    StockAnalysis     # 承接单股十日推演、归因、仓位建议
    Screener          # 承接 selector 阈值校准与推荐候选
    Review            # 承接每日归因、后验复盘、命中率复盘
    Monitor           # 承接关键价位、信号触发、规则提醒
  backend/app/
    api/              # 新增 decision / attribution / replay API
    services/         # 包装 a-stock 决策内核或迁移纯函数
    strategy/         # 接入 selector 为策略插件
    data_providers/   # 保持 TickFlow 主数据源，补充外部事件源

a-stock
  quant_system/
    selector/         # 迁移为 tickflow 策略评分插件
    attribution/      # 迁移为每日归因服务
    replay/           # 迁移为十日前视角滚动推演服务
    decision/         # 迁移为仓位场景操作建议服务
    impact/           # 迁移为公告/业绩/产业价格事件解释层
    contracts/        # 作为跨系统数据契约
```

## 3. 模块迁移映射

| a-stock 模块 | 现有能力 | tickflow 承接位置 | 迁移方式 | 优先级 |
|--------------|----------|-------------------|----------|--------|
| `replay/` | 十日前视角逐日滚动推演 | `backend/app/api/stock_analysis.py` + `frontend/src/pages/StockAnalysis.tsx` | 新增“十日推演”接口和面板 | P0 |
| `attribution/` | 昨日上涨/今日下跌根因归因 | `backend/app/api/market_recap.py` + `frontend/src/pages/Review.tsx` | 新增“每日归因”报告区 | P0 |
| `decision/` | 空仓/半仓/满仓操作建议 | `stock-analysis` 个股页 | 新增仓位场景建议卡片 | P0 |
| `selector/` | 候选股排序、阈值自动校准 | `backend/app/strategy/` + `api/screener.py` | 先以外部评分列接入，后续策略插件化 | P1 |
| `impact/` | 业绩、公告、产业价格事件影响 | `data_providers/custom/` + `stock-analysis` | 作为扩展数据源和解释证据 | P1 |
| `recommendation/` | 短/中/长线 5 股推荐 | `Screener` / `Dashboard` | 新增推荐榜单 API | P1 |
| `portfolio/` | 组合暴露、调仓计划 | `Monitor` / 后续 Portfolio 页 | 先只读展示，不接实盘 | P2 |
| `agent/` | 解释、审计、策略诊断 | `services/ai_provider.py` / AI 报告 | 复用 tickflow AI 通道，保留 policy guard | P2 |
| `registry/monitoring/` | 数据注册表、运行日志 | `Data` / `Monitor` | 后续补数据血缘页 | P2 |

## 4. 当前下一步唯一执行顺序

| 顺序 | 任务 | 产出 | 验收标准 |
|------|------|------|----------|
| 1 | 建立迁移契约 | `Tickflow-Migration-Plan.md` + 原需求文档版本更新 | 明确两边职责，不再继续从零补 a-stock Web |
| 2 | 梳理 tickflow API 插入点 | stock-analysis / market-recap / screener 三类接口清单 | 能说明每个 a-stock 模块接到哪个 API |
| 3 | 迁移每日归因首版 | `/api/decision/attribution` 或 `/api/market-recap/attribution` | 输入 symbol/date，输出上涨/下跌根因、证据、置信度 |
| 4 | 迁移十日推演首版 | `/api/decision/replay` 或 `/api/stock-analysis/replay` | 支持只用十日前可见数据滚动推演到今天 |
| 5 | 迁移仓位场景建议 | `/api/decision/position-advice` | 输出空仓、半仓、满仓三类次日策略，不直接下单 |
| 6 | selector 接入 Screener | 自定义策略或评分列 | 可以在 tickflow 选股页看到 a-stock 候选排序 |
| 7 | 接入事件数据 | 公告/业绩/产业价格/资金流作为扩展数据 | 归因和建议能引用事件证据 |
| 8 | 命中率闭环 | Review 页面展示建议后验结果 | 每条建议能追踪 1/5/10 日结果 |

## 5. 首轮接口草案

### 5.1 每日归因

```http
GET /api/decision/attribution?symbol=002xxx.SZ&as_of=2026-07-15
```

输出字段：

| 字段 | 说明 |
|------|------|
| `symbol` | 标的 |
| `as_of` | 分析日期 |
| `previous_move` | 昨日涨跌事实 |
| `current_move` | 今日涨跌事实 |
| `root_causes` | 根因列表：量价、趋势、大盘、资金、公告、业绩、产业价格 |
| `broken_logic` | 上涨逻辑是否被破坏 |
| `evidence` | 使用到的数据证据 |
| `confidence` | 低/中/高 |
| `limitations` | 数据限制 |

### 5.2 十日推演

```http
GET /api/decision/replay?symbol=002xxx.SZ&days=10
```

输出字段：

| 字段 | 说明 |
|------|------|
| `start_date` | 十日前视角日期 |
| `steps` | 每日推演记录 |
| `known_data_only` | 是否只使用当时可见数据 |
| `daily_view` | 每日判断、证据、风险、失效条件 |
| `today_review` | 推演到今天后的复盘 |

### 5.3 仓位场景建议

```http
GET /api/decision/position-advice?symbol=002xxx.SZ&as_of=2026-07-15
```

输出字段：

| 字段 | 说明 |
|------|------|
| `empty_position` | 空仓视角：是否等待、关注价位、触发条件 |
| `half_position` | 半仓视角：是否持有、加减仓条件、风险位 |
| `full_position` | 满仓视角：是否降低风险、观察价位 |
| `key_levels` | 支撑、压力、止损观察、失效位 |
| `next_day_plan` | 次日观察计划 |
| `disclaimer` | 非自动交易、非确定性预测说明 |

## 6. 保留与暂停

| 类别 | 处理 |
|------|------|
| a-stock CLI 与静态报告 | 保留为迁移期间对照基线，不继续扩展 UI |
| 自动实盘 | 跳过，不进入本阶段 |
| 科创板重型拉取 | 继续保持参考模式 |
| 纯研究模块 | 可继续保留在 a-stock，待稳定后再迁移 |
| tickflow 原有页面 | 不大改结构，优先在现有页面加增强区块 |

## 7. 风险与约束

| 风险 | 处理方式 |
|------|----------|
| 数据源口径不同 | 首轮以 tickflow enriched 数据为主，a-stock 输出只做补充解释 |
| 两边代码风格不同 | 先包装服务，再逐步迁移纯函数 |
| 投资建议合规风险 | 输出“指导性观察计划”，不输出自动下单指令 |
| TickFlow 数据源限制 | 保留外部事件数据和 AkShare 补充通道 |
| 开源项目声明限制 | 如需商业用途，先核对作者声明和数据源条款 |

## 8. 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-07-15 | 新增 tickflow 基座迁移梳理：明确 a-stock 作为决策增强内核，制定模块映射、接口草案和唯一执行顺序 |
