#!/bin/bash
# LogSentinel Docker 部署脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "LogSentinel Docker 部署"
echo "=========================================="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

echo "✅ Docker 环境检查通过"

# 解析参数
ACTION="${1:-up}"

case "$ACTION" in
    up)
        echo ""
        echo "🚀 启动服务..."
        docker compose up -d --build
        
        echo ""
        echo "⏳ 等待服务启动..."
        sleep 10
        
        echo ""
        echo "🔍 检查服务状态..."
        docker compose ps
        
        echo ""
        echo "=========================================="
        echo "✅ 部署完成！"
        echo ""
        echo "📌 服务地址："
        echo "   - 前端界面: http://localhost:3000"
        echo "   - 后端 API: http://localhost:8000"
        echo "   - API 文档: http://localhost:8000/docs"
        echo "   - Loki:     http://localhost:3100"
        echo ""
        echo "📌 常用命令："
        echo "   - 查看日志:   docker compose logs -f"
        echo "   - 停止服务:   ./scripts/docker-deploy.sh down"
        echo "   - 重启服务:   ./scripts/docker-deploy.sh restart"
        echo "=========================================="
        ;;
    down)
        echo "🛑 停止服务..."
        docker compose down
        echo "✅ 服务已停止"
        ;;
    restart)
        echo "🔄 重启服务..."
        docker compose restart
        echo "✅ 服务已重启"
        ;;
    logs)
        docker compose logs -f
        ;;
    status)
        docker compose ps
        ;;
    clean)
        echo "🧹 清理所有资源（包括数据卷）..."
        docker compose down -v --rmi local
        echo "✅ 清理完成"
        ;;
    *)
        echo "用法: $0 {up|down|restart|logs|status|clean}"
        echo ""
        echo "  up      - 构建并启动所有服务"
        echo "  down    - 停止所有服务"
        echo "  restart - 重启所有服务"
        echo "  logs    - 查看服务日志"
        echo "  status  - 查看服务状态"
        echo "  clean   - 清理所有资源（包括数据卷）"
        exit 1
        ;;
esac
