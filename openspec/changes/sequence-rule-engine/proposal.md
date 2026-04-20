## Why

当前系统仅支持单条件规则匹配（关键词/阈值），无法应对复杂的多步调故障诊断场景。在分布式系统中，许多关键事件需要多个独立日志事件按特定顺序或时间关系出现才能构成真正的告警。例如：(1) 服务启动失败需要先出现"Connection refused"，然后在30秒内出现"Max retries exceeded"；(2) 级联故障检测需要A宕机后5分钟内B也宕机才告警；(3) 否定关联检测需要"Error occurred"后3分钟内没有"Error recovered"则告警。

## What Changes

- **扩展规则数据模型**：从单一条件(pattern + threshold)演变为多条件步骤序列，每个步骤支持独立的日志模式、匹配次数和时间窗口约束
- **序列状态机制**：规则引擎需维护跨评估轮次的状态(SequenceState)，记录每条规则的哪些步骤已命中、命中时间戳，支持状态回滚(超时失效)
- **关联类型支持**：实现顺序关联(A→B)和否定关联(A→¬B)两种关系，支持配置T秒时间约束
- **前端规则编辑**：规则表单升级为多步骤表单UI，支持动态增删步骤、配置关联类型和时间窗口
- **评估引擎改造**：RuleEvaluator从平行匹配多规则升级为序列状态追踪，支持中间态告警(partial trigger)和序列重置

## Capabilities

### New Capabilities

- `sequence-rule-engine`: 支持多条件时序关联的规则引擎，包括顺序关联、否定关联及时间约束
- `sequence-state-persistence`: 规则执行状态持久化机制，支持跨轮次状态维护和超时失效
- `multi-step-rule-ui`: 前端多步骤规则表单，支持步骤增删、关联类型选择和时间窗口配置

### Modified Capabilities

- `rule-model`: 扩展Rule模型以支持steps数组和关联配置，保持向后兼容单条件规则
- `rule-engine-evaluator`: 升级评估器支持序列状态机制，现有单条件规则通过适配层继续工作
- `rule-crud-api`: 新增SequenceState查询端点，Rule CRUD保持兼容

## Impact

- **数据库**：新增SequenceState表，扩展Rule表schema
- **后端API**：/api/rules/* 端点新增fields，新增/api/sequence-states/* 查询端点
- **规则引擎**：evaluator.py核心逻辑重构，新增sequence_state_manager.py
- **前端**：RuleForm.tsx升级为多步骤表单，RuleList显示序列类型标签
- **依赖**：无新增第三方依赖
