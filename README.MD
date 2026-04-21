# LogSentinel - K8s 日志告警平台

基于 Loki 的 Kubernetes 日志告警系统，支持灵活的规则配置和实时告警。

## 部署方式

推荐用 Helm Umbrella Chart 一键部署到 K8s（含 PG / Redis / Loki）：

```bash
# 毕设答辩 / 本地 K3s
helm install logsentinel helm-charts/logsentinel \
  -f helm-charts/logsentinel/values-dev.yaml \
  -n logsentinel --create-namespace

# 生产环境
helm install logsentinel helm-charts/logsentinel \
  -f helm-charts/logsentinel/values-prod.yaml \
  -n logsentinel --create-namespace

# 查看访问地址
kubectl -n logsentinel get svc logsentinel-api logsentinel-frontend
```

访问地址（NodePort 默认）：
- 前端：`http://<NodeIP>:30881/`
- API docs：`http://<NodeIP>:30880/docs`
- WebSocket：`ws://<NodeIP>:30881/ws/alerts`

开发环境可用 `docker-compose up` 启动单副本 PG + Redis + Engine + API + 前端（不追求分布式验证）。

## 快速启动（本地开发）

### 前置条件

- Docker & Docker Compose
- Minikube（或其他 K8s 集群）
- Helm 3.x
- kubectl
- MinIO（已部署）

### 1. 部署 Loki Stack

首先在 K8s 集群中部署 Loki 和 Promtail：

```bash
# 添加 Grafana Helm 仓库
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# 部署 Loki（使用项目配置）
./scripts/setup-loki.sh
```

等待 Loki 部署完成：

```bash
kubectl get pods -n loki
```

### 2. 启动端口转发

让本地可以访问 Loki API：

```bash
kubectl port-forward -n loki svc/loki-gateway 3100:80 &
```

验证 Loki 可访问：

```bash
curl http://localhost:3100/loki/api/v1/labels
```

### 3. 启动 LogSentinel 服务

使用 Docker Compose 启动后端、引擎和前端：

```bash
docker-compose up -d --build
```

查看服务状态：

```bash
docker-compose ps
```

所有服务应显示为 `healthy` 或 `running`。

### 4. 验证服务

**后端 API**
```bash
curl http://localhost:8000/health
# 预期输出: {"status":"healthy","timestamp":"..."}
```

**前端界面**
```bash
open http://localhost:3000
```

**API 文档**
```bash
open http://localhost:8000/docs
```

### 5. 部署测试 Pod（可选）

生成测试日志用于验证告警功能：

```bash
kubectl create namespace demo
kubectl apply -f scripts/test-pod.yaml
```

等待日志被采集（约 30 秒），然后创建测试规则：

```bash
curl -X POST "http://localhost:8000/api/rules" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "测试错误告警",
    "enabled": true,
    "severity": "high",
    "selector_namespace": "demo",
    "match_type": "contains",
    "match_pattern": "ERROR",
    "threshold": 1,
    "group_by": ["namespace", "pod"],
    "cooldown_seconds": 300
  }'
```

查看告警：

```bash
curl http://localhost:8000/api/alerts | python3 -m json.tool
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 | 3000 | React 界面 |
| 后端 API | 8000 | FastAPI 服务 |
| Loki | 3100 | 日志查询（端口转发） |
| MinIO | 9000 | 对象存储（外部） |

## 查看日志

```bash
# 后端日志
docker logs -f logsentinel-backend

# 规则引擎日志（推荐）
docker logs -f logsentinel-engine

# 前端日志
docker logs -f logsentinel-frontend
```

## 停止服务

```bash
# 停止 Docker 容器
docker-compose down

# 停止端口转发
pkill -f "kubectl port-forward.*loki"

# 删除测试资源（可选）
kubectl delete namespace demo
```

## 卸载 Loki

```bash
helm uninstall loki -n loki
helm uninstall promtail -n loki
kubectl delete namespace loki
```

## 故障排查

### 后端无法连接 Loki

检查端口转发是否正常：
```bash
curl http://localhost:3100/loki/api/v1/labels
```

如果失败，重新启动端口转发：
```bash
kubectl port-forward -n loki svc/loki-gateway 3100:80
```

### 没有日志数据

检查 Promtail 状态：
```bash
kubectl get pods -n loki | grep promtail
kubectl logs -n loki -l app.kubernetes.io/name=promtail
```

### 告警未触发

查看引擎日志：
```bash
docker logs logsentinel-engine
```

确认规则已启用：
```bash
curl http://localhost:8000/api/rules
```

## 开发模式

如需修改代码并实时生效：

```bash
# 仅重启后端
docker-compose restart backend

# 仅重启引擎
docker-compose restart engine

# 前端开发模式（热重载）
cd frontend
npm run dev
```

## 技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite
- **前端**: React + TypeScript + Ant Design
- **日志**: Loki + Promtail
- **存储**: MinIO（对象存储）
- **部署**: Docker Compose + Kubernetes

## 更多文档

- [功能规格](specs/001-mvp-core-loop/spec.md)
- [快速开始](specs/001-mvp-core-loop/quickstart.md)
- [任务清单](specs/001-mvp-core-loop/tasks.md)
