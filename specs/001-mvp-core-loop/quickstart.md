# Quick Start Guide: MVP 核心闭环

**Feature**: 001-mvp-core-loop  
**Date**: 2026-02-04  
**目标**: 15-20 分钟内完成本地环境搭建并验证完整告警闭环

## 前置条件

### 必需环境

- **操作系统**: macOS
- **Minikube**: 已安装并运行
- **Helm**: 3.x+ (用于部署 Loki)
- **kubectl**: 已配置
- **Python**: 3.11+
- **Node.js**: 18+
- **Git**: 已安装

### 验证前置条件

```bash
# 验证 Minikube 运行状态
minikube status
# 如果未运行，执行: minikube start --cpus=2 --memory=4096 --driver=docker

# 验证 Helm 安装
helm version --short
# 如未安装: brew install helm

# 验证 kubectl
kubectl version --client

# 验证 Python 版本
python3 --version  # 应显示 3.11+

# 验证 Node.js 版本
node --version  # 应显示 18+
```

## 一、部署 Loki Stack

> **已迁移**：Loki 现已作为 `helm-charts/logsentinel` Umbrella Chart 的 subchart 随平台一起部署，不再需要独立部署到 `loki` namespace。详见仓库根目录 README。

```bash
helm install logsentinel helm-charts/logsentinel \
  -f helm-charts/logsentinel/values-dev.yaml \
  -n logsentinel --create-namespace
```

## 二、克隆项目并初始化

### 2.1 克隆仓库

```bash
git clone <repository-url>
cd logsentinel
git checkout 001-mvp-core-loop
```

### 2.2 初始化后端

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境（macOS/Linux）
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 创建数据目录
mkdir -p data

# 复制环境变量模板（如果存在）
[ -f .env.example ] && cp .env.example .env
```

编辑 `.env` 文件（如果不存在则创建），配置：

```
# 直接连接 loki 服务（使用 3102 端口）
LOKI_URL=http://localhost:3102
DATABASE_URL=sqlite:///./data/logsentinel.db
ENGINE_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
```

> **注意**：MVP 期用 3102 端口直连 loki 服务是为规避 httpx 502 兼容问题；P3 改用 aiohttp 后已解除该限制。

### 2.3 初始化数据库

```bash
# 当前目录：backend/
# 虚拟环境已激活

# 数据库会在首次运行时自动创建
# 如需手动初始化，可运行：
# python -c "from database.base import init_db; import asyncio; asyncio.run(init_db())"
```

### 2.4 初始化前端

```bash
cd ../frontend

# 安装依赖
npm install

# 复制环境变量模板（如果存在）
[ -f .env.example ] && cp .env.example .env
```

编辑 `.env` 文件（如果不存在则创建），配置：

```
VITE_API_URL=http://localhost:8000
```

## 三、启动服务

### 3.1 启动后端 API + 引擎（新终端 1）

```bash
cd backend
source venv/bin/activate

# 启动后端服务（包含引擎）
python -m backend.main
```

或使用 uvicorn：

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**验证**：访问 http://localhost:8000/docs 查看 API 文档

### 3.2 启动引擎（如果独立运行）

如果后端不包含引擎自动启动，在新终端中运行：

```bash
cd backend
source venv/bin/activate

# 启动规则引擎
python -m backend.engine.worker
```

### 3.3 启动前端服务（新终端 2）

```bash
cd frontend
npm run dev
```

**验证**：访问 http://localhost:5173 查看 Web 界面（Vite 默认端口）

## 四、部署测试 Pod

### 4.1 创建测试命名空间

```bash
kubectl create namespace demo
```

### 4.2 部署测试 Pod（持续输出 ERROR 日志）

使用提供的测试 Pod 配置：

```bash
kubectl apply -f scripts/test-pod.yaml
```

验证部署：

```bash
# 验证 Pod 运行
kubectl get pods -n demo

# 查看日志
kubectl logs -n demo error-log-generator -f
```

**预期输出**：每 10 秒输出一次包含 "ERROR" 的日志

### 4.3 验证 Loki 可查询到日志

等待 15-30 秒让 Promtail 采集日志，然后验证：

```bash
# 使用 curl 查询 Loki（注意端口为 3102）
curl -G "http://localhost:3102/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="demo"}' \
  --data-urlencode "limit=10"
```

**预期结果**：返回包含 "ERROR" 的日志条目

## 五、创建告警规则

### 5.1 通过 Web 界面创建规则

1. 访问 http://localhost:5173（或检查终端显示的实际端口）
2. 点击"规则管理"
3. 点击"创建规则"
4. 填写表单：
   - **规则名称**: 测试错误告警
   - **严重级别**: high
   - **命名空间**: demo
   - **匹配类型**: contains
   - **匹配模式**: ERROR
   - **时间窗口**: 0（不使用窗口）
   - **阈值**: 1
   - **分组维度**: namespace, pod
   - **冷却时间**: 300
5. 点击"保存"

### 5.2 通过 API 创建规则（可选）

使用 curl：

```bash
curl -X POST "http://localhost:8000/api/rules" \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

## 六、验证告警闭环

### 6.1 等待引擎执行

规则引擎默认每 30 秒执行一次，等待 60-90 秒后继续。

### 6.2 查看后端日志

在后端终端中，应看到类似以下的结构化日志：

```json
{
  "timestamp": "2026-02-04T08:30:15.123Z",
  "level": "info",
  "event": "rule_evaluated",
  "rule_id": 1,
  "rule_name": "测试错误告警",
  "matched": true,
  "log_count": 3
}

{
  "timestamp": "2026-02-04T08:30:15.456Z",
  "level": "info",
  "event": "alert_created",
  "alert_id": 1,
  "rule_id": 1,
  "fingerprint": "a1b2c3d4e5f6..."
}

{
  "timestamp": "2026-02-04T08:30:15.789Z",
  "level": "info",
  "event": "alert_notification",
  "rule_name": "测试错误告警",
  "severity": "high",
  "triggered_at": "2026-02-04T08:30:15.000Z",
  "hit_count": 1,
  "sample_log": {
    "timestamp": "2026-02-04T08:30:14.500Z",
    "content": "ERROR: Connection timeout to database",
    "namespace": "demo",
    "pod": "error-log-generator"
  }
}
```

### 6.3 查看 Web 界面

1. 访问前端界面（检查终端显示的实际端口）
2. 点击"告警管理"
3. 应看到一条新告警：
   - 规则名称: 测试错误告警
   - 严重级别: high
   - 命中次数: >= 1
   - 最后触发时间: 最近时间
4. 点击告警查看详情，应看到：
   - 首次触发时间
   - 最后触发时间
   - 累计命中次数
   - 样例日志（包含 "ERROR" 关键词）

### 6.4 验证告警合并

等待 1-2 分钟，刷新告警列表：

- 告警数量应保持为 1 条（同一 fingerprint 合并）
- 命中次数应增加（如 3、5、7...）
- 最后触发时间应更新为最新时间

### 6.5 验证冷却期

观察后端日志，在首次通知后的 5 分钟内（冷却期 300 秒），应只看到：

```json
{
  "event": "alert_updated",
  "alert_id": 1,
  "hit_count": 5,
  "notification_skipped": "cooldown active"
}
```

5 分钟后，如果告警再次命中，应看到新的通知日志。

## 七、自动化验证（可选）

使用提供的端到端验证脚本：

```bash
cd scripts
./verify-pipeline.sh
```

脚本会自动执行：
1. 检查所有服务健康状态
2. 部署测试 Pod
3. 验证 Loki 可查询到日志
4. 创建测试规则
5. 等待告警生成
6. 验证告警数据正确性
7. 清理测试资源

**预计执行时间**: 3-5 分钟

## 八、创建窗口阈值规则（可选）

### 8.1 创建高频错误规则

通过 Web 界面或 API 创建第二条规则：

```bash
curl -X POST "http://localhost:8000/api/rules" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "高频错误告警",
    "enabled": true,
    "severity": "critical",
    "selector_namespace": "demo",
    "selector_labels": null,
    "match_type": "contains",
    "match_pattern": "ERROR",
    "window_seconds": 60,
    "threshold": 3,
    "group_by": ["namespace", "pod"],
    "cooldown_seconds": 600
  }'
```

### 8.2 验证窗口阈值逻辑

等待 1-2 分钟后，查看告警列表：

- 应生成新的告警（不同 rule_id，不同 fingerprint）
- 仅当 60 秒内命中 >= 3 次时才生成告警
- 命中次数应准确反映窗口内的日志数量

## 九、停用规则

### 9.1 停用规则

1. 在 Web 界面规则列表中，点击"停用"按钮
2. 规则状态变为"已停用"

### 9.2 验证引擎停止评估

观察后端日志，应不再看到该规则的评估日志。

### 9.3 重新启用规则

1. 点击"启用"按钮
2. 规则状态变为"已启用"
3. 引擎恢复评估该规则

## 十、清理环境

### 10.1 删除测试 Pod

```bash
kubectl delete pod error-log-generator -n demo
kubectl delete namespace demo
```

### 10.2 停止服务

- 按 `Ctrl+C` 停止前端服务
- 按 `Ctrl+C` 停止后端服务
- 按 `Ctrl+C` 停止 Loki 端口转发

### 10.3 清理数据（可选）

```bash
# 删除数据库文件
rm -f backend/data/logsentinel.db
```

### 10.4 卸载 Loki（可选）

```bash
helm uninstall loki -n loki
helm uninstall promtail -n loki
kubectl delete namespace loki
```

## 十一、故障排查

### 11.1 Loki Pod 无法启动

**症状**：`kubectl get pods -n loki` 显示 Pod 处于 Pending 或 CrashLoopBackOff

**解决**：
1. 检查 Pod 状态：`kubectl describe pod -n loki <pod-name>`
2. 查看 Pod 日志：`kubectl logs -n loki <pod-name>`
3. 常见问题：
   - MinIO PVC 创建失败：检查 Minikube 存储类
   - 资源不足：增加 Minikube 资源 `minikube start --cpus=4 --memory=8192`

### 11.2 后端无法连接 Loki

**症状**：后端日志显示 "Connection refused" 或 "Timeout"

**解决**：
1. 验证 Loki 端口转发是否运行：
   ```bash
   # 检查端口是否被占用
   lsof -i :3102
   ```
2. 验证 Loki 可访问：
   ```bash
   curl http://localhost:3102/loki/api/v1/labels
   ```
3. 检查 `.env` 文件中的 `LOKI_URL` 配置（应为 `http://localhost:3102`）

### 11.3 Promtail 无法采集日志

**症状**：Loki 查询不到任何日志

**解决**：
1. 检查 Promtail 状态：
   ```bash
   kubectl get pods -n loki -l app.kubernetes.io/name=promtail
   kubectl logs -n loki -l app.kubernetes.io/name=promtail
   ```
2. 验证 Promtail 配置的 Loki 地址正确
3. 检查 Promtail values 文件中的 `config.clients.url`

### 11.4 引擎未生成告警

**症状**：规则已创建且启用，但告警列表为空

**排查步骤**：
1. 检查后端日志，查找 "rule_evaluated" 事件
2. 验证 Loki 可查询到日志：
   ```bash
   curl -G "http://localhost:3102/loki/api/v1/query_range" \
     --data-urlencode 'query={namespace="demo"}' \
     --data-urlencode "limit=10"
   ```
3. 检查规则的 `last_query_time` 是否更新：
   ```bash
   curl http://localhost:8000/api/rules/1
   ```
4. 检查测试 Pod 是否正常输出日志：
   ```bash
   kubectl logs -n demo error-log-generator
   ```

### 11.5 前端无法加载数据

**症状**：前端界面显示加载错误或空白

**解决**：
1. 验证后端服务运行：访问 http://localhost:8000/docs
2. 检查浏览器控制台错误信息（F12）
3. 验证 `.env` 文件中的 `VITE_API_URL` 配置
4. 检查 CORS 配置（后端应允许前端端口）

### 11.6 脚本执行权限问题

**症状**：运行脚本时提示 "Permission denied"

**解决**：
```bash
chmod +x scripts/*.sh
```

## 十二、下一步

完成快速启动后，可以：

1. **阅读技术文档**：
   - [plan.md](./plan.md) - 技术实施计划
   - [data-model.md](./data-model.md) - 数据模型定义
   - [research.md](./research.md) - 技术调研与决策

2. **查看 API 文档**：
   - 访问 http://localhost:8000/docs（Swagger UI）
   - 查看 [contracts/rules-api.yaml](./contracts/rules-api.yaml)
   - 查看 [contracts/alerts-api.yaml](./contracts/alerts-api.yaml)

3. **开始开发**：
   - 执行 `/speckit.tasks` 生成任务清单
   - 按照 Phase 1-5 顺序实施功能

4. **运行测试**：
   ```bash
   cd backend
   pytest tests/
   ```

---

## 关键文件清单

- `scripts/verify-pipeline.sh` - 端到端验证脚本
- `scripts/test-pod.yaml` - 测试 Pod 配置
- `helm-charts/logsentinel/` - Umbrella Chart（Loki/Promtail 已作为 subchart 内置）

---

**预计完成时间**: 15-20 分钟（包括 Loki 部署）

**成功标志**: 
- ✅ Loki 和 Promtail 部署成功
- ✅ 后端服务正常运行
- ✅ 前端界面可访问
- ✅ 规则创建成功
- ✅ 告警自动生成
- ✅ 通知输出到控制台
- ✅ Web 界面可查看告警详情

**演示视频**：
完整演示可参考 `verify-pipeline.sh` 自动化脚本的执行流程。