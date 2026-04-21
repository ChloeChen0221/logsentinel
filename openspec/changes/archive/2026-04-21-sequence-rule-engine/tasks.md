## 1. 数据库模型扩展

- [x] 1.1 在 `backend/models/rule.py` 新增 `rule_type` 字段（Enum: keyword/threshold/sequence，默认 keyword）和 `correlation_type` 字段（Optional Enum: sequence/negative）
- [x] 1.2 新增 `backend/models/rule_step.py`，定义 `RuleStep` 模型（id, rule_id外键级联删除, step_order, match_type, match_pattern, window_seconds, threshold）
- [x] 1.3 新增 `backend/models/sequence_state.py`，定义 `SequenceState` 模型（id, rule_id外键级联删除, current_step, step_timestamps JSON, started_at, expires_at）
- [x] 1.4 在 `backend/models/__init__.py` 导出新模型
- [x] 1.5 更新 `backend/database/base.py`，确保新表在 `create_all()` 时被创建

## 2. Pydantic Schema 扩展

- [x] 2.1 在 `backend/schemas/rule.py` 新增 `RuleStepSchema`（step_order, match_type, match_pattern, window_seconds, threshold）
- [x] 2.2 扩展 `RuleCreate` / `RuleUpdate` Schema，新增 `rule_type`、`correlation_type`、`steps: Optional[List[RuleStepSchema]]` 字段
- [x] 2.3 扩展 `RuleResponse` Schema，新增同上字段，`steps` 默认返回空列表
- [x] 2.4 新增 `SequenceStateResponse` Schema（rule_id, current_step, step_timestamps, started_at, expires_at）

## 3. API 层扩展

- [x] 3.1 更新 `backend/api/rules.py` 的 POST `/api/rules`：创建 Rule 后，若 rule_type=sequence 则批量插入 RuleStep 记录
- [x] 3.2 更新 PUT `/api/rules/{id}`：删除旧 RuleStep 后重新插入新步骤
- [x] 3.3 更新 GET `/api/rules/{id}`：eager load 关联 steps，按 step_order 排序后序列化返回
- [x] 3.4 新增 `backend/api/sequence_states.py`，实现 GET `/api/sequence-states?rule_id={id}` 端点
- [x] 3.5 在 `backend/main.py` 注册新路由

## 4. 规则引擎核心改造

- [x] 4.1 新增 `backend/engine/sequence_state_manager.py`，实现 `load_or_create(rule_id)`、`advance(state, step_index, timestamp)`、`reset(state)`、`is_expired(state)` 函数
- [x] 4.2 在 `backend/engine/evaluator.py` 中，将现有 `evaluate_rule()` 逻辑提取为 `_evaluate_single_condition()`
- [x] 4.3 新增 `_evaluate_sequence(rule)` 函数，实现：加载 SequenceState → 超时检测与重置 → 按 current_step 查询 Loki 并匹配对应 RuleStep → 命中则推进步骤 → 根据 correlation_type 判断是否触发告警
- [x] 4.4 在 `evaluate_rule()` 入口根据 `rule.rule_type` 分发到 `_evaluate_single_condition()` 或 `_evaluate_sequence()`
- [x] 4.5 更新 `load_enabled_rules()` 以 eager load `rule.steps` 关系

## 5. 前端规则表单

- [x] 5.1 在 `frontend/src/pages/RuleForm.tsx` 新增 `rule_type` 下拉字段（选项：关键词、阈值、序列规则），切换类型时显示/隐藏对应字段区域
- [x] 5.2 实现步骤列表组件：支持动态添加/删除步骤行，每行包含 match_type、match_pattern、window_seconds、threshold 输入
- [x] 5.3 新增 `correlation_type` 选择器（顺序关联 / 否定关联），附带语义说明文字
- [x] 5.4 表单验证：sequence 类型规则至少需要2个步骤，步骤的 match_pattern 不能为空
- [x] 5.5 更新 `frontend/src/services/rules.ts` 的类型定义，新增 `RuleStep` 接口和 Rule 中的新字段

## 6. 前端规则列表

- [x] 6.1 在 `frontend/src/pages/RuleList.tsx` 的规则类型列，新增对 `rule_type=sequence` 的标签展示（区别于现有"关键词"/"阈值"标签）

## 7. 端到端验证

- [x] 7.1 启动服务，通过 Swagger UI 手动创建一条 sequence 类型规则（顺序关联），验证数据库中 rule_steps 表有记录
- [x] 7.2 验证引擎评估循环能正确加载序列规则并初始化 SequenceState
- [x] 7.3 验证前端表单能完整创建/编辑序列规则并回显步骤数据
