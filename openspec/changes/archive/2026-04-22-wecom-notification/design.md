## Context

LogSentinel 当前通知链路：`evaluator → alert_manager.create_or_update_alert → enqueue_notification(channel="console") → notifier_worker → ConsoleNotifier.send` 。除 console 外无真实外发渠道。

通知链路已具备的能力（不可退化）：
- `asyncio.Queue(10000)` 解耦评估与发送
- `notifications` 表状态机 `pending → sent/failed`
- CAS 抢占（`UPDATE ... WHERE status='pending'`）
- 3 次指数退避重试（1s/2s/4s）
- 启动补偿扫表（24h 内 pending 重新入队）

企业微信群机器人 Webhook 官方约束：
- 端点 `POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}`，`application/json`
- 单机器人 **20 条/分钟**；超限返回 `errcode=45009`
- text ≤ 2048 字节；markdown ≤ 4096 字节
- 无签名机制；泄露即被盗用
- 成功 `{"errcode":0,"errmsg":"ok"}`；其他 errcode 视为失败

## Goals / Non-Goals

**Goals:**
- 规则可配置 N 个企微群机器人，触发时并行发送并独立追踪发送状态
- 一个群挂不影响其他群（扇出成 N 条 notification，独立 CAS 独立重试）
- 告警风暴场景下，依赖规则 `cooldown_seconds` 兜底 + 客户端限流避免触发 45009
- 保留 console 渠道作为无配置时的默认行为，向后兼容现有规则
- 提供测试发送接口，让用户在配置前验证 webhook 可达

**Non-Goals:**
- 钉钉 / 邮件 / 飞书等其他渠道（留给后续 change）
- 企微 application 消息（需 access_token 流程，比 webhook 复杂）
- Redis 分布式 Semaphore（并发控制用进程内 Semaphore，毛刺可接受）
- webhook URL 加密存储 / K8s Secret 管理（毕设场景不做）
- 告警聚合/合并（方案 C：依赖 cooldown_seconds，不做时间窗聚合）
- 通知模板自定义（固定 Markdown 模板，规则层不可改）

## Decisions

### D1：扇出时机 —— 入队时扇出（方案 X）

**选型对比：**

| 维度 | 方案 X（入队时扇出） | 方案 Y（消费时扇出） |
|---|---|---|
| notification 粒度 | 一规则一 alert N 条记录 | 一 alert 一条记录 |
| 状态建模 | 每 channel 独立 pending/sent/failed | 需 JSONB 表达部分成功 |
| CAS 语义 | 零改动复用 | 失效，需重新设计 |
| 单 channel 故障隔离 | ✅ | ❌ |
| 补偿扫表 | 零改动 | 需重写识别"哪个 channel 还没发" |

**选 X**：复用现有所有机制，唯一代价是 notifications 表行数 ×N。

### D2：渠道配置存储 —— `rules.notify_config JSONB`

**选型对比：**

| 维度 | JSONB 内联（选） | 独立 channels 表 + 关联表 |
|---|---|---|
| DDL | 1 字段 | 2 表 + FK |
| 复用 | ❌ 同一 webhook 要重复填 | ✅ |
| UI 复杂度 | 规则表单内嵌列表 | 额外渠道管理页面 |
| 答辩可讲性 | 实现直白 | "范式化设计"有料 |

**选 JSONB**：毕设场景复用需求低，抢时间。未来需要复用时再 migrate 到独立表。

`notify_config` 结构：
```json
[
  {
    "type": "wecom",
    "name": "开发群",
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
    "mentioned_mobile_list": ["13800000000"]
  }
]
```

### D3：快照存储 —— `notifications.channel_config JSONB`

触发时把当次使用的渠道配置快照写入 `notifications.channel_config`，原因：
- consumer 从表中取任务时不再反查 `rules.notify_config`（无竞态）
- 用户后续修改渠道不影响已入队通知的发送目标（审计一致性）
- 失败重发时能拿到当时的完整配置

### D4：限流 —— Redis 分布式滑动窗口 + 进程内并发 Semaphore + fail-open 兜底

**背景（实测修订）**：原设计仅使用进程内 `AsyncLimiter(20, 60)`，上线后 §10.5 压测暴露两个问题：
1. 每副本独立计数，总速率 = 副本数 × 20，2 API 副本时会突破企微 20/min 配额
2. 瞬时 25 并发触发企微未文档化的错误码 `errcode=45033 api concurrent out of limit`

**方案选型对比**：

| 算法 | 精度 | 复杂度 | 决策 |
|---|---|---|---|
| 滑动窗口 ZSET（选） | 精确"60s 内 ≤ 20" | 中；复用现有 `RedisWindowCounter` 模式 | ✅ |
| 固定窗口 INCR+EXPIRE | 跨窗口边界可能双倍突破 | 低 | ❌ 精度不够 |
| Token Bucket Lua | 平滑速率 | 高；需手写 Lua | ❌ 毕设不需要 |

**Redis Key 设计**：

```
Key 命名：       wecom:rl:{md5(webhook_url)[:12]}   （避免明文 webhook 进 key）
数据结构：       ZSET
member：         "{ts_ms}:{uuid8}"                   （同毫秒不去重）
score：          ts_ms                               （毫秒时间戳）
TTL：            120s                                （窗口 60s × 2，空闲自动回收）

写入流程（acquire）：
  1. ZREMRANGEBYSCORE key 0 (now_ms - 60_000)       清理 60s 外旧记录
  2. ZCARD key                                      取当前计数
  3. 若 < 20：ZADD + EXPIRE；放行
  4. 若 ≥ 20：ZRANGE 0 0 WITHSCORES 取最老记录 → 计算需等待时间 → asyncio.sleep → 重试

并发控制：
  进程内 dict[url_key] -> asyncio.Semaphore(2)，每个 webhook 同时最多 2 个 in-flight 请求
  值 = 2：行业常见且实测不会触 45033；想更保守可调到 1

失败兜底：
  Redis 任何异常 → 记 warning 日志 → 退化到进程内 AsyncLimiter(20,60) 
  （fail-open：优先保障告警送达，宁可偶尔短暂突破配额也不要错过告警）
```

**为什么双层限流（Redis + 进程内 AsyncLimiter 兜底）**：
- 正常路径：Redis 精确控制总速率 + Semaphore 控制并发
- Redis 故障：AsyncLimiter 至少保证单副本不突破（多副本全挂时最坏情况 = 副本数 × 20，和改造前持平，不恶化）

**为什么不用 Redis 分布式 Semaphore**：
- 并发窗口在毫秒级，Redis 往返延迟 ≥ 1-5ms，额外开销大
- 进程内 Semaphore 即使副本级独立，3 副本 × 2 = 6 的总并发对企微也是安全值

### D5：错误码处理

| errcode | 含义 | 处理 |
|---|---|---|
| 0 | 成功 | CAS mark sent |
| 45009 | 超频（速率） | backoff 60s 后重试 |
| 45033 | 并发过高 | backoff 5s 后重试（retriable=True） |
| 其他 != 0 | 鉴权/参数错误 | **不重试**，直接 failed，`error_message` 记录 errcode+errmsg |
| HTTP 5xx / 超时 | 临时网络 | 默认 1s/2s/4s backoff 重试 |
| HTTP 4xx | 客户端错误 | 不重试，直接 failed |

**决策**：鉴权错误重试只会浪费请求。`_send_once` 返回 `{"success":False,"retriable":False,"error":"..."}` 新增 `retriable` 字段，consumer 据此决定是否进入重试循环。

### D6：消息格式化 —— 固定 Markdown 模板

```
# 🔴 [严重] 规则名称
━━━━━━━━━━━━━━━━━━━━

**规则**: <rule_name>  (ID=<rule_id>)
**时间**: 2026-04-22 10:30:45
**命中**: 12 次（首次 10:28:15 / 最近 10:30:45）
**分组**: namespace=prod-api pod=api-7d8f9c

**样本日志**:
> <sample log content, 截断到 400 字节>

<可选：@手机号>
```

Severity 染色用企微 `<font color="...">`：
- `critical` / `error` → `warning`（橙红）
- `warning` → `comment`（灰）
- `info` → `info`（绿）

超过 4096 字节按字节数截断 sample_log 优先。

### D7：Fallback 到 console

`enqueue_notification` 签名改为：
```python
async def enqueue_notification(
    db: AsyncSession,
    alert_id: int,
    rule_name: str,
    channels: list[dict],  # 从 rule.notify_config 传入
) -> list[int]:
    if not channels:
        channels = [{"type": "console", "name": "console"}]
    # 扇出循环...
```

consumer 端 registry：
```python
NOTIFIERS = {"console": ConsoleNotifier, "wecom": WecomNotifier}
```

### D8：测试发送 API

```
POST /api/channels/test
body: {"webhook_url": "...", "mentioned_mobile_list": [...]}
```

同步调用企微 webhook，发送固定文案 `LogSentinel 连通性测试 <ISO 时间>`；根据 errcode 返回 200/400。不走队列，即时反馈。

## Risks / Trade-offs

- **[Risk] webhook URL 明文落 DB** → 用户可控，部署到毕设环境风险可接受；PG 仅 ClusterIP 暴露；**Mitigation**：API 返回时 mask 为 `***key` 尾 4 位，前端编辑时需用户重新粘贴
- **[Risk] Redis 故障导致限流失效** → fail-open 退化到进程内 `AsyncLimiter`，短时间可能突破配额触发 45009；**Mitigation**：告警链路优先送达，errcode=45009 走 60s backoff 自愈；Redis 已是毕设单点依赖，故障概率可控
- **[Risk] 进程内 Semaphore 在多副本场景并发总数 = 副本数 × 2** → 3 副本总并发 6，远低于企微并发上限；**Mitigation**：实测验证不触发 45033 即可
- **[Risk] JSONB 配置改动无版本管理** → 用户修改 `notify_config` 后，已排队但未发送的通知仍按老快照发 → **设计已规避**：D3 通过 `channel_config` 快照保证一致性
- **[Risk] 测试发送被滥用成 DDoS 跳板** → 用户通过 UI 反复点测试按钮 → **Mitigation**：API 侧加 `AsyncLimiter(5, 60)` 每 IP 限速（可选，视前端防抖足够则不做）
- **[Risk] 扇出后 notifications 表行数增长 × N** → 毕设场景 N ≤ 3，影响有限；查询已用 `(status, created_at)` 索引加速
- **[Risk] 存量 rule 的 notify_config 缺失字段** → Pydantic schema `default=[]`；migration 默认值 `'[]'::jsonb`；evaluator 读取时 `rule.notify_config or []` 防御

## Migration Plan

1. Alembic revision：
   - `rules` 添 `notify_config JSONB NOT NULL DEFAULT '[]'::jsonb`
   - `notifications` 添 `channel_config JSONB NOT NULL DEFAULT '{}'::jsonb`
2. 部署顺序：**migration → backend → frontend**；backend 老代码读新字段不报错（默认值兜底），滚动升级安全
3. 回滚：`alembic downgrade -1` drop 两个字段；代码回滚到前一 commit；已发送的通知记录不受影响

## Open Questions

无。所有决策已在 explore 阶段和用户确认。
