#!/bin/sh
# 在容器启动前执行数据库迁移
# 用法：
#   - K8s: 作为 initContainer command
#   - docker-compose: 作为 api 服务 entrypoint 第一步
set -e
cd "$(dirname "$0")/.."
echo "[migrate] alembic upgrade head ..."
alembic upgrade head
echo "[migrate] done"
