# Data Model: MVP 核心闭环

**Feature**: 001-mvp-core-loop  
**Date**: 2026-02-04  
**Phase**: 1 - Design & Contracts

## 概述

本文档定义 MVP 阶段的核心数据模型，包括实体关系、字段定义、验证规则和状态转换。

## 实体关系图

```
┌─────────────┐
│    Rule     │
│  (告警规则)  │
└──────┬──────┘
       │ 1
       │
       │ N
┌──────▼──────┐
│    Alert    │
│  (告警记录)  │
└──────┬──────┘
       │ 1
       │
       │ N
┌──────▼──────┐
│Notification │
│  (通知记录)  │
└─────────────┘
```

**关系说明**：
- 一条 Rule 可以生成多条 Alert（1:N）
- 一条 Alert 可以触发多次 Notification（1:N）
- Alert 通过 `fingerprint` 去重，同一 fingerprint 只有一条记录

## 实体定义

### 1. Rule（告警规则）

**用途**：定义日志匹配条件和告警触发逻辑

**字段定义**：

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INTEGER | PRIMARY KEY | AUTO | 规则 ID |
| name | VARCHAR(255) | NOT NULL | - | 规则名称 |
| enabled | BOOLEAN | NOT NULL | true | 启用状态 |
| severity | VARCHAR(20) | NOT NULL | - | 严重级别（low/medium/high/critical） |
| selector_namespace | VARCHAR(255) | NOT NULL | - | 命名空间选择器 |
| selector_labels | JSON | NULLABLE | null | 标签选择器（如 {"app": "myapp"}） |
| match_type | VARCHAR(20) | NOT NULL | - | 匹配类型（contains/regex） |
| match_pattern | TEXT | NOT NULL | - | 匹配模式（关键词或正则表达式） |
| window_seconds | INTEGER | NOT NULL | 0 | 时间窗口（秒，0 表示不使用窗口） |
| threshold | INTEGER | NOT NULL | 1 | 阈值（窗口内命中次数） |
| group_by | JSON | NOT NULL | - | 分组维度（如 ["namespace", "pod"]） |
| cooldown_seconds | INTEGER | NOT NULL | 300 | 冷却时间（秒） |
| last_query_time | DATETIME | NULLABLE | null | 上次查询时间（引擎使用） |
| created_at | DATETIME | NOT NULL | NOW() | 创建时间 |
| updated_at | DATETIME | NOT NULL | NOW() | 更新时间 |

**验证规则**：
- `name` 不能为空，长度 1-255
- `severity` 必须是 `low`、`medium`、`high`、`critical` 之一
- `selector_namespace` 不能为空
- `match_type` 必须是 `contains` 或 `regex`
- `match_pattern` 不能为空
- `window_seconds` 必须 >= 0
- `threshold` 必须 >= 1
- `group_by` 必须是非空数组，元素为 `namespace`、`pod`、`container` 之一
- `cooldown_seconds` 必须 >= 0
- 如果 `match_type` 为 `regex`，`match_pattern` 必须是合法的正则表达式

**索引**：
- PRIMARY KEY: `id`
- INDEX: `enabled`（用于引擎加载已启用规则）

**SQLAlchemy 模型**：
```python
from sqlalchemy import Column, Integer, String, Boolean, Text, JSON, DateTime
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime

class Base(DeclarativeBase):
    pass

class Rule(Base):
    __tablename__ = "rules"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    severity = Column(String(20), nullable=False)
    selector_namespace = Column(String(255), nullable=False)
    selector_labels = Column(JSON, nullable=True)
    match_type = Column(String(20), nullable=False)
    match_pattern = Column(Text, nullable=False)
    window_seconds = Column(Integer, nullable=False, default=0)
    threshold = Column(Integer, nullable=False, default=1)
    group_by = Column(JSON, nullable=False)
    cooldown_seconds = Column(Integer, nullable=False, default=300)
    last_query_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 2. Alert（告警记录）

**用途**：记录规则触发后生成的告警实例

**字段定义**：

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INTEGER | PRIMARY KEY | AUTO | 告警 ID |
| rule_id | INTEGER | NOT NULL, FK | - | 关联规则 ID |
| fingerprint | VARCHAR(64) | NOT NULL, UNIQUE | - | 告警指纹（SHA256） |
| severity | VARCHAR(20) | NOT NULL | - | 严重级别 |
| status | VARCHAR(20) | NOT NULL | active | 状态（active，MVP 固定，仅作未来扩展预留） |
| first_seen | DATETIME | NOT NULL | - | 首次触发时间 |
| last_seen | DATETIME | NOT NULL | - | 最后触发时间 |
| hit_count | INTEGER | NOT NULL | 1 | 累计命中次数 |
| group_by | JSON | NOT NULL | - | 分组维度值（如 {"namespace": "demo", "pod": "xxx"}） |
| sample_log | JSON | NOT NULL | - | 最新一条匹配日志 |
| last_notified_at | DATETIME | NULLABLE | null | 上次通知时间（冷却期使用） |
| created_at | DATETIME | NOT NULL | NOW() | 创建时间 |
| updated_at | DATETIME | NOT NULL | NOW() | 更新时间 |

**验证规则**：
- `rule_id` 必须存在于 Rule 表
- `fingerprint` 必须唯一
- `severity` 必须是 `low`、`medium`、`high`、`critical` 之一
- `status` MVP 阶段固定为 `active`（仅作未来扩展预留，当前不参与业务逻辑）
- `first_seen` <= `last_seen`
- `hit_count` >= 1
- `group_by` 必须是非空对象
- `sample_log` 必须包含 `timestamp`、`content`、`namespace`、`pod` 字段

**索引**：
- PRIMARY KEY: `id`
- UNIQUE INDEX: `fingerprint`
- INDEX: `rule_id`
- INDEX: `last_seen DESC`（用于列表排序）

**SQLAlchemy 模型**：
```python
from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship

class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id"), nullable=False)
    fingerprint = Column(String(64), nullable=False, unique=True)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    hit_count = Column(Integer, nullable=False, default=1)
    group_by = Column(JSON, nullable=False)
    sample_log = Column(JSON, nullable=False)
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    rule = relationship("Rule", backref="alerts")
```

**sample_log 结构**：
```json
{
  "timestamp": "2026-02-04T08:30:15.123Z",
  "content": "ERROR: Connection timeout",
  "namespace": "demo",
  "pod": "test-pod-123",
  "container": "app"
}
```

### 3. Notification（通知记录）

**用途**：记录告警触发的通知历史

**字段定义**：

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
|--------|------|------|--------|------|
| id | INTEGER | PRIMARY KEY | AUTO | 通知 ID |
| alert_id | INTEGER | NOT NULL, FK | - | 关联告警 ID |
| notified_at | DATETIME | NOT NULL | - | 通知时间 |
| channel | VARCHAR(50) | NOT NULL | - | 通知渠道（console/email/webhook） |
| content | TEXT | NOT NULL | - | 通知内容（JSON 格式） |
| status | VARCHAR(20) | NOT NULL | - | 发送状态（success/failed） |
| error_message | TEXT | NULLABLE | null | 错误信息（失败时记录） |
| created_at | DATETIME | NOT NULL | NOW() | 创建时间 |

**验证规则**：
- `alert_id` 必须存在于 Alert 表
- `channel` 必须是 `console`、`email`、`webhook` 之一
- `status` 必须是 `success` 或 `failed`
- `content` 必须是合法的 JSON 字符串

**索引**：
- PRIMARY KEY: `id`
- INDEX: `alert_id`
- INDEX: `notified_at DESC`

**SQLAlchemy 模型**：
```python
class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    notified_at = Column(DateTime, nullable=False)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # 关系
    alert = relationship("Alert", backref="notifications")
```

**content 结构**：
```json
{
  "rule_name": "测试错误告警",
  "severity": "high",
  "triggered_at": "2026-02-04T08:30:15.000Z",
  "hit_count": 5,
  "sample_log": {
    "timestamp": "2026-02-04T08:30:14.500Z",
    "content": "ERROR: Connection timeout",
    "namespace": "demo",
    "pod": "test-pod-123"
  }
}
```

## 状态转换

### Rule 状态

```
┌─────────┐
│ enabled │
│ = true  │
└────┬────┘
     │
     │ 用户停用
     ▼
┌─────────┐
│ enabled │
│ = false │
└────┬────┘
     │
     │ 用户启用
     ▼
┌─────────┐
│ enabled │
│ = true  │
└─────────┘
```

**说明**：
- 规则创建时默认 `enabled = true`
- 用户可随时启用/停用规则
- 停用的规则不参与引擎评估

### Alert 状态

```
┌─────────┐
│  active │ ◄──┐
└────┬────┘    │
     │         │
     │ 持续命中 │
     └─────────┘
```

**说明**：
- MVP 阶段所有告警保持 `active` 状态
- 不实现 `resolved` 状态
- 告警通过 `last_seen` 时间判断是否活跃

**MVP 阶段 status 字段设计说明**：
- MVP 阶段不实现告警生命周期管理（ack/resolved）
- `status` 字段固定为 `active`，仅作为未来扩展预留字段
- 当前阶段 `status` 不参与任何业务判断逻辑

### Notification 状态

```
┌─────────┐
│ pending │
└────┬────┘
     │
     ├─ 发送成功 ──► ┌─────────┐
     │              │ success │
     │              └─────────┘
     │
     └─ 发送失败 ──► ┌─────────┐
                    │ failed  │
                    └─────────┘
```

**说明**：
- 通知创建时状态为 `pending`（可选实现）
- 发送成功后更新为 `success`
- 发送失败后更新为 `failed`，记录错误信息

## 数据完整性约束

### 外键约束

```sql
ALTER TABLE alerts
ADD CONSTRAINT fk_alerts_rule_id
FOREIGN KEY (rule_id) REFERENCES rules(id)
ON DELETE CASCADE;

ALTER TABLE notifications
ADD CONSTRAINT fk_notifications_alert_id
FOREIGN KEY (alert_id) REFERENCES alerts(id)
ON DELETE CASCADE;
```

**说明**：
- 删除规则时，级联删除关联的告警记录
- 删除告警时，级联删除关联的通知记录

### 唯一性约束

```sql
ALTER TABLE alerts
ADD CONSTRAINT uq_alerts_fingerprint
UNIQUE (fingerprint);
```

**说明**：
- 保证同一 fingerprint 只有一条告警记录

## 数据迁移

### 初始迁移脚本

**文件**：`backend/database/migrations/001_initial_schema.sql`

```sql
-- 创建 rules 表
CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    severity VARCHAR(20) NOT NULL,
    selector_namespace VARCHAR(255) NOT NULL,
    selector_labels JSON,
    match_type VARCHAR(20) NOT NULL,
    match_pattern TEXT NOT NULL,
    window_seconds INTEGER NOT NULL DEFAULT 0,
    threshold INTEGER NOT NULL DEFAULT 1,
    group_by JSON NOT NULL,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    last_query_time DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rules_enabled ON rules(enabled);

-- 创建 alerts 表
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL,
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    severity VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    first_seen DATETIME NOT NULL,
    last_seen DATETIME NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1,
    group_by JSON NOT NULL,
    sample_log JSON NOT NULL,
    last_notified_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rule_id) REFERENCES rules(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_alerts_fingerprint ON alerts(fingerprint);
CREATE INDEX idx_alerts_rule_id ON alerts(rule_id);
CREATE INDEX idx_alerts_last_seen ON alerts(last_seen DESC);

-- 创建 notifications 表
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    notified_at DATETIME NOT NULL,
    channel VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);

CREATE INDEX idx_notifications_alert_id ON notifications(alert_id);
CREATE INDEX idx_notifications_notified_at ON notifications(notified_at DESC);
```

### 使用 Alembic 管理迁移

**配置**：`backend/alembic.ini`

**迁移命令**：
```bash
# 生成迁移脚本
alembic revision --autogenerate -m "Initial schema"

# 执行迁移
alembic upgrade head

# 回滚迁移
alembic downgrade -1
```

## 示例数据

### 规则示例

```json
{
  "name": "测试错误告警",
  "enabled": true,
  "severity": "high",
  "selector_namespace": "demo",
  "selector_labels": null,
  "match_type": "contains",
  "match_pattern": "ERROR",
  "window_seconds": 0,
  "threshold": 1,
  "group_by": ["namespace", "pod"],
  "cooldown_seconds": 300
}
```

```json
{
  "name": "高频错误告警",
  "enabled": true,
  "severity": "critical",
  "selector_namespace": "demo",
  "selector_labels": {"app": "myapp"},
  "match_type": "contains",
  "match_pattern": "ERROR",
  "window_seconds": 60,
  "threshold": 3,
  "group_by": ["namespace", "pod"],
  "cooldown_seconds": 600
}
```

### 告警示例

```json
{
  "rule_id": 1,
  "fingerprint": "a1b2c3d4e5f6...",
  "severity": "high",
  "status": "active",
  "first_seen": "2026-02-04T08:30:00.000Z",
  "last_seen": "2026-02-04T08:35:15.000Z",
  "hit_count": 5,
  "group_by": {
    "namespace": "demo",
    "pod": "test-pod-123"
  },
  "sample_log": {
    "timestamp": "2026-02-04T08:35:14.500Z",
    "content": "ERROR: Connection timeout",
    "namespace": "demo",
    "pod": "test-pod-123",
    "container": "app"
  },
  "last_notified_at": "2026-02-04T08:30:00.000Z"
}
```

---

**下一步**：生成 API 合约文档（OpenAPI 规范）。