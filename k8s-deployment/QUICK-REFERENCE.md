# 快速参考：Loki 直连配置

## 🎯 关键配置

### 端口配置

| 服务 | 端口 | 用途 |
|------|------|------|
| loki 服务（直连）| 3102 | ✅ **当前使用** - 引擎查询 |
| loki-gateway | 3100 | ⚠️ 不使用（httpx 兼容性问题）|
| 后端 API | 8000 | Web API 服务 |
| 前端 | 5173 | React 开发服务器 |

### 环境变量

```bash
export LOKI_URL=http://localhost:3102
export ENGINE_INTERVAL_SECONDS=30
export LOG_LEVEL=INFO
```

## 🚀 启动命令

### 1. 启动 Loki 端口转发（终端 1）

```bash
kubectl port-forward -n loki svc/loki 3102:3100
```

### 2. 启动后端 API（终端 2）

```bash
cd /path/to/logsentinel
export PYTHONPATH="$(pwd)"
backend/venv/bin/python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动规则引擎（终端 3）

**方式 A：使用脚本（推荐）**

```bash
cd scripts
./start-engine.sh
```

**方式 B：手动启动**

```bash
cd /path/to/logsentinel
export PYTHONPATH="$(pwd)"
export LOKI_URL="http://localhost:3102"
backend/venv/bin/python -m backend.engine.worker
```

### 4. 启动前端（终端 4，可选）

```bash
cd frontend
npm run dev
```

## ✅ 验证清单

```bash
# 1. 检查 Loki 连接
curl http://localhost:3102/loki/api/v1/labels

# 2. 检查后端 API
curl http://localhost:8000/health

# 3. 检查告警列表
curl http://localhost:8000/api/alerts

# 4. 运行完整验证
cd scripts
./verify-pipeline.sh
```

## 📝 代码修改说明

### 已修改的文件

1. **backend/engine/loki_client.py**
   - ✅ 将 `httpx` 改为 `requests`
   - ✅ 解决 502 Bad Gateway 问题

2. **backend/requirements.txt**
   - ✅ 添加 `requests==2.31.0`

3. **specs/001-mvp-core-loop/quickstart.md**
   - ✅ 更新端口号（3100 → 3102）
   - ✅ 更新端口转发命令

4. **scripts/verify-pipeline.sh**
   - ✅ 更新默认 LokiUrl（3100 → 3102）

5. **脚本文件（Mac/Linux版本）**
   - ✅ `scripts/setup-loki.sh` - Loki 部署脚本
   - ✅ `scripts/start-engine.sh` - 引擎启动脚本
   - ✅ `scripts/verify-pipeline.sh` - 管道验证脚本

## 🔧 故障排查

### 问题：引擎报 502 错误

**原因**：使用了 gateway (端口 3100)

**解决**：
1. 停止当前端口转发
2. 使用直连命令：`kubectl port-forward -n loki svc/loki 3102:3100`
3. 确保 LOKI_URL=http://localhost:3102

### 问题：找不到 requests 模块

**解决**：

```bash
cd backend
source venv/bin/activate
pip install requests
```

### 问题：规则评估失败

**检查步骤**：
1. Loki 端口转发是否运行
2. LOKI_URL 环境变量是否正确
3. 测试 Pod 是否正常输出日志

## 📚 相关文档

- [quickstart.md](../specs/001-mvp-core-loop/quickstart.md) - 完整启动指南
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - 详细故障排查
- [tasks.md](../specs/001-mvp-core-loop/tasks.md) - 任务清单

## 🎯 为什么直连 loki？

1. ✅ **避免 httpx 502 问题**：requests 库兼容性更好
2. ✅ **性能更优**：少一层 nginx 转发
3. ✅ **功能完整**：SingleBinary 模式下效果相同
4. ✅ **配置简单**：不需要处理 gateway 复杂性

详细说明见：[TROUBLESHOOTING.md](./TROUBLESHOOTING.md#为什么会有-502-问题)
