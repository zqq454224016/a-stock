# a-stock Architecture v2

## 1. 设计目标

- 最终交付自动量化交易系统：策略选股后结合实时行情、账户持仓和风险状态，输出可执行交易操作信息；人工授权券商接口后支持自动报单。
- 实时操作信息必须包含标的、时间、动作、目标数量或仓位、订单类型、价格/触发条件、有效期、策略版本、风险检查和失效原因。
- 研究、影子交易和真实交易共用同一确定性指令契约；仅执行权限不同，禁止页面展示逻辑另行生成买卖结论。
- 数据源可替换，领域逻辑不依赖 SDK。
- 存储可替换，任务不拼接物理路径。
- 原始、标准、特征、研究产物分层。
- 全市场 Universe 与手工代码使用同一选择接口。
- AI 只读取 Evidence Package。
- AI 不得生成评分、目标仓位或买卖指令；实时指令由确定性策略与风控引擎计算。
- 旧模块通过兼容适配层逐步迁移，不进行一次性重写。

## 2. 包结构

```text
quant_system/
├── domain/              # 纯业务对象和契约，无 I/O
│   ├── datasets.py
│   └── evidence.py
├── application/         # 用例编排
│   └── universe_service.py
├── infrastructure/      # SDK、网络、文件、数据库实现
│   ├── providers/
│   └── storage/
├── interfaces/          # CLI / 内部 HTTP 页面
├── factors/             # Feature 层计算
├── backtest/            # Research 层验证
├── ai/                  # Evidence Package 消费者
└── legacy compatibility # 现有 tasks/data_source/apps，逐步迁移
```

## 3. 依赖方向

```text
interfaces → application → domain
                      ↑
          infrastructure implements ports
```

禁止：

- `domain` 导入 pandas、TickFlow、HTTP 或具体文件路径。
- `application` 导入内部页面组件。
- Provider 直接生成 AI 提示词。
- AI 直接调用 Provider。
- 回测读取没有 `known_at` 的事件和财务数据。

## 4. 数据目录

```text
assets/data/
├── raw/{provider}/{dataset}/{date}/
├── normalized/{dataset}/{date}/
├── features/{feature_set}/{date}/
├── research/{run_id}/
├── evidence/{symbol}/{evidence_id}.json
├── manifests/{dataset}.json
└── legacy/                       # 迁移完成前的旧 JSON
```

现有 `stocks/`、`factors/` 等路径暂时保留。新数据集只写新目录；完成消费者迁移和双写核对后再移动旧数据。

## 5. 迁移策略

1. 新建 Domain 契约和 Application 用例。
2. 现有 TickFlow API 通过 Infrastructure Adapter 接入。
3. `universe_job` 和内部页面先迁移。
4. 行情、因子、回测、预测依次迁移。
5. 用户通过页面或命令行显式输入代码；默认边界为 TickFlow Universe。
6. 删除旧兼容层前必须满足：无生产引用、无 CLI 入口、契约测试覆盖替代路径。

## 6. 删除准则

代码只有同时满足以下条件才删除：

- 无运行入口。
- 无模块引用。
- 无数据迁移用途。
- 已有替代实现。
- 完整测试通过。

本轮可删除：旧报表生成脚本、静态页面、失效 console 注册和旧兼容抓取脚本。旧量化任务仍有测试与调用方，不属于无用代码。

## 7. 单命令流水线约束

- `./run.sh all` 是唯一的端到端数据与研究流水线入口。
- 新增数据源、标准化、特征、研究或 AI 产物时，只在 `run_all_pipeline` 中注册阶段，不新增 CLI 子命令。
- `serve`、`config` 等保留为服务启动和本机配置入口，不属于数据功能流水线。
- 内部页面可以触发局部刷新，但生产全量运行和验收必须通过 `./run.sh all`。
- 每个阶段必须幂等、可记录 manifest；数据权限不足时写入明确的 `unavailable` 状态，不静默跳过。
- 全市场行情必须使用批量接口并遵守套餐限频；禁止用多线程逐股请求冲击供应商接口。
- TickFlow 免费档历史日 K 走 `TickFlow.free()`/free-api，配置 Key 后也不能错误地把免费历史批量请求发送到付费端点。
