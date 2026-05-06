## ADDED Requirements

### Requirement: Promtail DaemonSet 部署
系统 SHALL 在 logsentinel namespace 部署 Promtail DaemonSet，采集所有 K8s Pod 的 stdout/stderr 日志，并以 `namespace`、`pod`、`container`、`app`（或 `job`）作为 stream label 推送到 Loki。

#### Scenario: Loki 收到 Pod 日志
- **WHEN** Promtail DaemonSet 部署完成且 Pod 处于 Running 状态
- **THEN** `curl http://logsentinel-loki:3100/loki/api/v1/labels` 返回包含 `namespace`、`pod`、`container` 的 label 列表

#### Scenario: Engine 能查到真实日志
- **WHEN** Promtail 正在采集且 K8s 集群中有 Pod 产生日志
- **THEN** Engine 日志中出现 `total_logs > 0` 的 `Rule evaluated` 条目

#### Scenario: 轻量资源配置
- **WHEN** 部署 Promtail DaemonSet
- **THEN** Promtail Pod 的 resource requests 配置为 CPU ≤ 50m、内存 ≤ 64Mi（此为配置值，实际稳态用量可能更低）
