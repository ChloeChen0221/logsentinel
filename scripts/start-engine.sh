#!/bin/bash
# 启动规则引擎 Worker
# 使用正确的 LOKI_URL 配置（直接连接 loki 服务）

set -e

# 默认参数
LOKI_URL="${1:-http://localhost:3102}"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'

echo -e "${CYAN}=== Starting LogSentinel Engine ===${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

# 检查 Python 虚拟环境
VENV_PYTHON="${PROJECT_ROOT}/backend/venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo -e "${RED}Error: Virtual environment not found at $VENV_PYTHON${NC}"
    echo -e "${YELLOW}Please run: python3 -m venv backend/venv${NC}"
    exit 1
fi

# 检查 Loki 连接
echo -e "\n${YELLOW}Checking Loki connection...${NC}"
if curl -s --connect-timeout 5 "${LOKI_URL}/loki/api/v1/labels" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Loki is accessible at $LOKI_URL${NC}"
else
    echo -e "${RED}✗ Cannot connect to Loki at $LOKI_URL${NC}"
    echo -e "\n${YELLOW}Please ensure Loki port-forward is running:${NC}"
    echo "  kubectl port-forward -n loki svc/loki 3102:3100"
    echo -e "\n${YELLOW}Or specify a different URL:${NC}"
    echo "  ./start-engine.sh http://localhost:3100"
    exit 1
fi

# 设置环境变量
export PYTHONPATH="${PROJECT_ROOT}"
export LOKI_URL="${LOKI_URL}"

echo -e "\n${YELLOW}Configuration:${NC}"
echo "  PYTHONPATH: $PYTHONPATH"
echo "  LOKI_URL: $LOKI_URL"

# 启动引擎
echo -e "\n${YELLOW}Starting engine...${NC}"
echo -e "${GRAY}Press Ctrl+C to stop${NC}\n"

"$VENV_PYTHON" -m backend.engine.worker
