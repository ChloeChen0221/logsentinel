# Loki Gateway 502 问题排查

## 问题描述

使用 Python httpx 库通过 loki-gateway 查询时返回 502 Bad Gateway，但使用 requests 库或 curl 正常。

## 原因分析

httpx 和 nginx gateway 之间的 HTTP 协议协商问题，可能涉及：
- HTTP/2 vs HTTP/1.1
- Keep-Alive 连接处理
- 某些 HTTP 头的处理

## 解决方案

### 方案 A：使用 requests 库（已实施）

修改 `backend/engine/loki_client.py`，将 httpx 替换为 requests：

```python
import requests  # 替代 httpx

# 同步请求，在 async 函数中使用 asyncio.to_thread
response = requests.get(url, params=params, timeout=self.timeout)
```

### 方案 B：调整 Gateway 配置

修改 `k8s-deployment/loki-values.yaml`，在 gateway 配置中添加：

```yaml
gateway:
  enabled: true
  nginxConfig:
    httpSnippet: |
      # 禁用 HTTP/2
      http2_max_field_size 16k;
      http2_max_header_size 32k;
    serverSnippet: |
      # 增加超时和缓冲
      proxy_connect_timeout 60s;
      proxy_send_timeout 60s;
      proxy_read_timeout 60s;
      proxy_buffering off;
      # 强制使用 HTTP/1.1
      proxy_http_version 1.1;
      proxy_set_header Connection "";
```

### 方案 C：直接连接 loki 服务（当前方案）

```bash
# 端口转发到 loki 服务而不是 gateway
kubectl port-forward -n loki svc/loki 3102:3100

# 配置
export LOKI_URL=http://localhost:3102
```

## 验证方法

```bash
# 测试 httpx
python backend/test_loki.py

# 测试 requests  
python backend/test_loki_requests.py

# 测试 curl
curl "http://localhost:3100/loki/api/v1/labels"
```

## 生产环境建议

1. **开发/测试环境**：使用方案 A + C（当前配置）
2. **生产环境**：实施方案 B 修复 gateway，或继续使用方案 A

## 性能影响

| 方案 | 延迟 | 功能 | 扩展性 |
|------|------|------|--------|
| 直接连接 loki | 低 | 完整 | 受限（单副本）|
| 通过 gateway | 中 | 完整+ | 好（支持多副本）|

## 当前配置说明

- **SingleBinary 模式**：loki 和 gateway 都指向同一个 pod
- **直接连接影响**：在当前配置下几乎没有影响
- **建议**：开发阶段保持当前配置，生产部署时评估是否需要 gateway
