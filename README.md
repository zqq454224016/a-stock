# a-stock

面向 A 股的本地数据、研究与**推荐策略**内核。当前阶段默认使用 TickFlow 获取日 K、公开源获取实时行情，并可复用当前机器已经登录的 Codex CLI 处理研究数据。

最终目标是：策略完成全市场选股后，输出带证据、价格区间、有效期、风险检查和失效条件的推荐与操作信息，供人工决策参考。本地纸面执行模拟仅用于校验 T+1、涨跌停、费用与部分成交等约束。**当前方案不接入券商、不自动报单。** AI 只处理数据，不生成评分或交易指令。

## 安装

```bash
./setup.sh
```

TickFlow Key 保存在本机配置文件 `config/local.json`。可直接编辑，也可通过命令安全写入：

```bash
./run.sh config --tickflow-key "你的 Key"
./run.sh config --tickflow-key "你的 Key" --tickflow-base-url "自定义地址"
```

配置使用仅当前用户可读写的 `0600` 权限，任务日志会隐藏密钥。TickFlow 是全市场历史日 K 主源；公开 HTTP 数据源补充财务、事件和情绪。Tushare 当前无可用免费额度，自动流程默认禁用。

飞书机器人 Webhook 同样保存在 `config/local.json`，后台迭代仅在状态或执行动作发生变化时同步进度，避免每五分钟重复刷屏。通知只包含任务名、成功/失败状态和下一次检查时间，不包含任何密钥或完整异常请求。

统一流水线还会使用无需密钥的公开备用源：

- 腾讯财经：批量实时行情、PE/PB、市值、换手率和涨跌停价，用于行情新鲜度检查与跨源核验。
- 东方财富 `push2ex`：涨停、炸板、跌停和昨日涨停池，串行限流后生成确定性的市场情绪数据。
- 新浪财经：仅为最终推荐候选补充资产负债表、利润表和现金流量表。
- 东方财富数据中心：仅为最终候选补充融资融券、限售解禁和大宗交易。
- 上交所、深交所：保存每日官方龙虎榜证据，作为第三方龙虎榜的备用核验源。

公开源补充默认开启。可用 `PUBLIC_SUPPLEMENT_ENABLED=0` 关闭；`EASTMONEY_MIN_INTERVAL_SEC` 控制东财请求最小间隔，默认 1.2 秒；`CANDIDATE_FINANCIAL_LIMIT` 控制补全三表的候选上限，默认 10。公开端点失败不会阻断主流水线，而会在 `assets/data/public_supplement/status.json` 留下明确状态。

## 使用

```bash
./run.sh stock 600519                    # TickFlow 同步并生成结构化分析数据
./run.sh diagnose 600519                 # 使用当前 Codex 登录态进行 AI 诊股
./run.sh diagnose 600519 --focus "关注趋势持续性"
./run.sh serve                          # 打开 http://127.0.0.1:8080
./run.sh all                             # 唯一数据流水线：基础数据、研究与 AI 产物
```

未指定股票代码时，`stock` 从 TickFlow 全市场股票池同步；页面也支持直接输入任意六位股票代码或按名称搜索，不再依赖自选股。主要输出：

- 个股数据：`assets/data/stocks/{code}.json`
- AI 诊股：`assets/data/ai_diagnosis/{code}.md`
- AI 股票研究候选：`assets/data/ai_recommendations/latest.md`
- AI 候选固定计算证据：`assets/data/ai_recommendations/evidence.json`
- 全市场半自动趋势策略：`assets/data/strategy/index.json`
- 过去五年后台策略验证：`assets/data/strategy_backtest/status.json`
- 自动迭代门禁：`assets/data/iteration/status.json`
- 后台迭代心跳：`assets/data/iteration/worker_status.json`
- AI 数据获取方案：`assets/data/iteration/data_acquisition_advice.md`
- 其他任务：继续写入 `assets/data/` 下对应 JSON
- 上市/暂停/退市证券主数据：`assets/data/normalized/market.instruments/security_master.json`
- 腾讯批量行情：`assets/data/normalized/market.quotes.tencent/latest.json`
- 涨跌停市场情绪：`assets/data/normalized/market.limit_pool.sentiment/latest.json`
- 候选完整三表：`assets/data/normalized/financial.candidate_statements/{code}.json`
- 候选资金与筹码事件：`assets/data/normalized/market.candidate_capital_events/{code}.json`
- 官方龙虎榜：`assets/data/normalized/market.dragon_tiger.official/{trade_date}.json`

内部页面提供全市场同步、单股诊断和“AI 股票研究候选”入口。荐股流程先由本地脚本完成全市场筛选、评分和指标计算，只把有限候选的结构化证据交给当前 Codex 解释；Codex 不得重算分数或新增标的。报告末尾附带不可由 AI 改写的“固定计算附录”，完整结构化证据同时写入 `evidence.json`。数据不足时允许不推荐，不会为凑数降低门槛。

`diagnose` 直接调用 `codex exec`，无需额外 API Key，但要求本机已安装并登录 Codex CLI。调用运行在临时只读沙箱中，不授予 Codex 修改项目文件的能力。

旧 `reports/` HTML 页面不再生成；原静态视图模块及报表生成脚本已移除。

## 后台迭代与日志

`./run.sh all` 完成后自动启动单实例后台工作器。默认每 5 分钟检查一次依赖；发现本地全市场数据落后于最近交易日时，会自动启动一次可断点续跑的全量刷新。新交易日数据完成后，再按依赖顺序执行趋势计算、五年离线验证、稳健策略候选赛和推荐。AI 只生成数据获取方式。

若 TickFlow 免费历史域名不可用，后台会优先使用腾讯收盘快照补齐最新一根日线：根据“本地前复权上一收盘 / 腾讯原始上一收盘”推导当期缩放比例，再合并 OHLCV。该路径只处理已收盘交易日，并保留来源与缩放比例供审计。

巡检日志默认只输出异常、每 250 只的进度和最终汇总，不再逐只打印正常股票。额外权限板块（科创板、创业板、北交所）不会进入重型巡检与研究链路。

后台文件：

- PID：`assets/data/iteration/worker.pid`
- 状态：`assets/data/iteration/worker_status.json`
- 日志：`assets/data/iteration/worker.log`
- 停止：创建 `assets/data/iteration/worker.stop`

新版架构与逐步执行路线：

- [Architecture v2](docs/Architecture-v2.md)
- [A股推荐策略迭代计划](docs/Automated-Trading-Iteration-Plan.md)（已放弃券商自动交易）
- [数据获取 Prompt v1](docs/prompts/Data-Acquisition-Prompt-v1.md)
