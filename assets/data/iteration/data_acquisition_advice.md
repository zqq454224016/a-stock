# AI 数据获取方案

> Prompt `1.0.0` · 契约评分 100/100 · 通过

优先补齐财务数据点时语义并定位质量错误；TickFlow能力与正式来源接口均须验证，不处理策略验证指标。

## D001 · 上市公司财务披露点时数据 · P0

- 状态：verify
- 证据：financial_dataset.status, financial_dataset.count, financial_dataset.period, iteration.data.point_in_time_financial_status, configured_sources.tickflow
- 字段：security_id, report_period, report_type, announcement_id, published_at, effective_from, revision_no, statement_type, field_name, field_value, source_name, source_record_id, fetched_at, raw_snapshot_hash
- 时间语义：as_of, published_at, known_at, effective_from, fetched_at
- 授权：现在可执行：核验已配置TickFlow的接口目录、字段说明、配额和现有70条记录。需要授权：如需Tushare，由人工完成账号配置、权限确认及费用审批；不得在流程中传递凭证。正式来源若要求协议或白名单，也须人工申请。

执行步骤：
1. 导出现有70条记录的非敏感字段清单、主键、时间字段和来源标识
2. 核对TickFlow已授权接口文档，确认财务报表、公告时间、修订链、分页和配额能力
3. 建立点时财务最小schema及不可变原始快照目录
4. 以小批证券和单一报告期验证分页、复合游标、幂等和修订保留
5. 与巨潮或交易所正式披露目录进行覆盖和时间交叉核验
6. 通过验收后按报告期分批回填，并记录每批次游标、失败项和快照哈希

验收条件：
- 每条入库记录均可追溯到source_name、source_record_id、fetched_at和raw_snapshot_hash
- 每条记录均具有明确的published_at与known_at，无法确定者被隔离并标记原因
- 相同游标区间重复同步不产生非版本化重复记录
- 历史修订可按announcement_id或等价正式标识重建完整版本链
- 现有70条记录均完成来源、主键、时间语义和覆盖状态核对
- 正式披露对账差异均形成可复现的缺失、解析失败或待验证清单

## D002 · 数据质量异常明细与采集血缘 · P0

- 状态：actionable
- 证据：iteration.data.quality_summary.error, iteration.data.quality_summary.factor_blocked, iteration.data.quality_summary.warning, iteration.data.quality_total
- 字段：check_id, dataset, record_key, severity, error_code, error_message, source_name, source_record_id, as_of, published_at, known_at, fetched_at, raw_snapshot_hash, pipeline_run_id, first_seen_at, last_seen_at, resolution_status
- 时间语义：as_of, published_at, known_at, fetched_at
- 授权：无需新增外部授权即可先检查本地质量明细和采集血缘；若日志访问受内部权限控制，由人工授予只读访问。外部复核仅使用已配置TickFlow或公开正式来源。

执行步骤：
1. 导出当前质量汇总对应的逐条异常清单
2. 为每条异常补齐数据集、记录主键、检查规则和采集运行标识
3. 关联原始快照、来源记录及全部时间字段
4. 按可重试获取失败、schema失败、时序失败和来源差异分类
5. 仅对可重试获取失败执行增量重抓，并生成新批次记录
6. 重新运行相同确定性检查并保留修复前后结果

验收条件：
- 当前2个error、2个factor_blocked和5个warning均有唯一明细记录或明确的血缘缺失记录
- 逐条明细重新聚合后与quality_total及quality_summary在同一运行批次内一致
- 每次重抓均产生新的fetched_at、pipeline_run_id和可追溯快照
- 异常状态变更可由相同check_id的确定性复检复现
- 无法复核的记录保持隔离，不被静默标记为正常

## D003 · 历史行情采集覆盖与游标元数据 · P1

- 状态：verify
- 证据：iteration.data.max_history_bars, iteration.data.universe_count, configured_sources.tickflow
- 字段：security_id, trade_date, bar_frequency, open, high, low, close, volume, amount, source_name, source_record_id, as_of, fetched_at, raw_snapshot_hash
- 时间语义：as_of, fetched_at, published_at, known_at
- 授权：现在可执行：核验TickFlow接口说明、分页响应和本地同步日志。需要授权：若现有授权不覆盖所需历史范围，由人工联系提供方确认升级；Tushare须人工配置和审批。不得自动购买或接受协议。

执行步骤：
1. 定位max_history_bars为1250的统计口径和产生环节
2. 选择少量证券检查首尾日期、分页参数、响应总量和游标日志
3. 确认上限属于数据可用范围、权限配额、接口分页还是本地截断
4. 仅在确认可获取更多数据后实施按日期分片的增量回填
5. 记录每个证券的覆盖起止日期、缺口类型、最后成功游标和快照哈希

验收条件：
- 能够以日志或接口说明确定1250条上限的唯一原因
- 每个已检查证券均有覆盖起止日期、频率、来源和最后成功游标
- 重复执行同一日期分片不会产生重复主键
- 分页抽样不存在边界日期遗漏或重复
- 如需额外权限，系统保持未授权状态且生成明确人工申请清单
